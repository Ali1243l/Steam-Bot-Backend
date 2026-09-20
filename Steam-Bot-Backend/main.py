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
SUPABASE_KEY = os.getenv("SUPABASE_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
IMAP_HOST = os.getenv("DEFAULT_IMAP_SERVER", "imap.example.com").strip()
TARGET_DASHBOARD_URL = os.getenv("TARGET_DASHBOARD_URL", "https://example.com/settings").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.warning("[CONFIG] Supabase credentials not found in environment variables.")

app = FastAPI(
    title="Automation Integration Bridge",
    version="1.0.0",
    description="Asynchronous orchestrator for database-driven browser tasks.",
)
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    supabase = get_supabase_client()
    logger.info(f"[PIPELINE:START] Beginning pipeline for record ID: {record_id}")

    try:
        # Step 1: تحديث حالة الحساب إلى قيد المعالجة (محجوز)
        supabase.table("stock_accounts").update({
            "status": "reserved",
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", record_id).execute()

        runner = AutomationRunner()
        
        task_payload = {
            "account_identifier": account_data.get("steam_username"),
            "account_secret": account_data.get("steam_password"),
            "original_email": account_data.get("original_email"),
            "email_password": account_data.get("email_password"),
            "target_contact": target_contact
        }

        # Step 2: تشغيل المتصفح لتنفيذ الدخول واستخراج الكود وتغيير الإيميل
        await runner.execute_task(TARGET_DASHBOARD_URL, task_payload)

        # Step 3: تحديث الحساب إلى مستخدم بعد النجاح
        logger.info(f"[PIPELINE:COMPLETE] Successfully processed task. Marking record {record_id} as 'used'.")
        supabase.table("stock_accounts").update({
            "status": "used",
            "assigned_game": "Email Updated",
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", record_id).execute()

    except Exception as exc:
        logger.error(f"[PIPELINE:ERROR] Task execution failed for record {record_id}: {exc}")
        try:
            supabase.table("stock_accounts").update({
                "status": "available",
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", record_id).execute()
        except Exception as update_err:
            logger.error(f"[SUPABASE:FAIL] Could not set error status: {update_err}")
    finally:
        if 'runner' in locals():
            await runner.close()


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
