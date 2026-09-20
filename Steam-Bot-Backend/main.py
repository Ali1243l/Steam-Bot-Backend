"""
main.py - Central Automation Orchestrator Service
Exposes a FastAPI endpoint to process tasks, coordinate Supabase record transitions,
and link IMAP token parsing with the headless browser runner.
"""

import os
import asyncio
import logging
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field

from fastapi import FastAPI, BackgroundTasks, HTTPException, status
from supabase import create_client, Client

# Import local modular engines
from browser_engine import AutomationRunner
from imap_helper import fetch_verification_code

# Configure structured logging
logger = logging.getLogger("orchestrator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Load environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", os.getenv("SUPABASE_ANON_KEY", "")).strip()
IMAP_HOST = os.getenv("DEFAULT_IMAP_SERVER", "imap.example.com").strip()
TARGET_DASHBOARD_URL = os.getenv("TARGET_DASHBOARD_URL", "https://example.com/settings").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.warning("[CONFIG] Supabase credentials not found in environment variables.")

app = FastAPI(
    title="Automation Integration Bridge",
    version="1.0.0",
    description="Asynchronous orchestrator for database-driven browser tasks.",
)


# Request and Response Schemas
class ProcessTaskRequest(BaseModel):
    target_contact: str = Field(..., description="The contact/email string to update via automation")
    order_reference: Optional[str] = Field(None, description="Optional external order identifier")
    sender_filter: Optional[str] = Field(
        default="noreply@example.com",
        description="Filter incoming email sender for verification extraction",
    )


class TaskResponse(BaseModel):
    status: str
    message: str
    account_id: Optional[str] = None
    order_reference: Optional[str] = None
    dispatched_at: str


def get_supabase_client() -> Client:
    """Initializes and returns a Supabase database client."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


async def execute_task_pipeline(
    record_id: str,
    account_data: dict,
    target_contact: str,
    sender_filter: str,
) -> None:
    """
    Background worker that runs the full automation sequence:
    1. Mark account as 'reserved'
    2. Poll for verification token via IMAP (non-blocking thread)
    3. Launch browser runner and execute form submission
    4. Update account state in Supabase ('used' or 'error')
    """
    supabase = get_supabase_client()
    logger.info(f"[PIPELINE:START] Beginning pipeline for record ID: {record_id}")

    try:
        # Step 1: Set state to 'reserved' to avoid race conditions with other workers
        supabase.table("stock_accounts").update({
            "status": "reserved",
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", record_id).execute()

        email_user = account_data.get("original_email")
        email_pass = account_data.get("email_password") or account_data.get("steam_password")

        if not email_user or not email_pass:
            raise ValueError(f"Record {record_id} lacks valid email credentials.")

        # Step 2: Fetch verification token using the IMAP helper in a separate thread
        logger.info(f"[PIPELINE:IMAP] Querying {IMAP_HOST} for incoming verification code...")
        verification_token = await asyncio.to_thread(
            fetch_verification_code,
            email_address=email_user,
            password=email_pass,
            imap_server=IMAP_HOST,
            sender_filter=sender_filter,
            timeout_seconds=30,
        )

        if not verification_token:
            raise RuntimeError(f"Failed to obtain verification token for {email_user}.")

        # Step 3: Initialize browser automation and execute form update
        logger.info(f"[PIPELINE:BROWSER] Token acquired: {verification_token}. Launching browser...")
        runner = AutomationRunner()
        workflow_success = await runner.execute_form_flow(
            target_url=TARGET_DASHBOARD_URL,
            verification_token=verification_token,
            new_contact_value=target_contact,
        )

        if not workflow_success:
            raise RuntimeError("Browser workflow execution reported failure.")

        # Step 4: Finalize account state as 'used'
        logger.info(f"[PIPELINE:COMPLETE] Successfully processed task. Marking record {record_id} as 'used'.")
        supabase.table("stock_accounts").update({
            "status": "used",
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", record_id).execute()

    except Exception as exc:
        logger.error(f"[PIPELINE:ERROR] Task execution failed for record {record_id}: {exc}")
        # Reset or mark error state so inventory remains auditable
        try:
            supabase.table("stock_accounts").update({
                "status": "error",
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", record_id).execute()
        except Exception as update_err:
            logger.error(f"[SUPABASE:FAIL] Could not set error status: {update_err}")


@app.post("/api/process-task", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def process_task(payload: ProcessTaskRequest, background_tasks: BackgroundTasks):
    """
    Main dispatch endpoint:
    - Finds the next available inventory account from Supabase.
    - Dispatches the async automation pipeline in the background.
    - Returns an immediate confirmation response with the assigned account ID.
    """
    try:
        supabase = get_supabase_client()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database configuration error: {str(e)}",
        )

    # Fetch one 'available' record ordered by oldest first (FIFO)
    query_result = (
        supabase.table("stock_accounts")
        .select("id, steam_username, steam_password, original_email, email_password, status")
        .eq("status", "available")
        .order("created_at", desc=False)
        .limit(1)
        .execute()
    )

    records = query_result.data
    if not records:
        logger.warning("[DISPATCH] No available accounts found in Supabase stock_accounts table.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No stock accounts currently available with status 'available'.",
        )

    target_record = records[0]
    record_id = target_record["id"]

    logger.info(f"[DISPATCH] Assigning record {record_id} ({target_record.get('steam_username')})")

    # Queue execution pipeline without blocking the HTTP client
    background_tasks.add_task(
        execute_task_pipeline,
        record_id=record_id,
        account_data=target_record,
        target_contact=payload.target_contact,
        sender_filter=payload.sender_filter,
    )

    return TaskResponse(
        status="queued",
        message="Task queued successfully for background execution.",
        account_id=record_id,
        order_reference=payload.order_reference,
        dispatched_at=datetime.utcnow().isoformat(),
    )


@app.get("/healthz", tags=["Monitoring"])
async def health_check():
    """Simple health check endpoint for VPS uptime monitors or load balancers."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


if __name__ == "__main__":
    import uvicorn
    # Bind to 0.0.0.0 for VPS / Docker container routing
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)