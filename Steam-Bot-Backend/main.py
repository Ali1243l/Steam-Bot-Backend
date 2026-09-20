import os
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client

from browser_engine import AutomationRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("orchestrator.main")

# Supabase Configurations
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
TARGET_DASHBOARD_URL = os.getenv("TARGET_DASHBOARD_URL", "https://help.steampowered.com/en/wizard/HelpChangeEmail/").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.warning("[CONFIG] Supabase credentials not found in environment variables.")

def get_supabase_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(
    title="Automation Integration Bridge",
    version="1.0.0",
    description="Asynchronous orchestrator for database-driven browser tasks."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Schemas
class ProcessTaskRequest(BaseModel):
    target_contact: str = Field(..., description="The target email to set on Steam")
    order_reference: Optional[str] = Field(None, description="Optional external order identifier")
    sender_filter: Optional[str] = Field(
        default="noreply@example.com",
        description="Filter incoming email sender"
    )
    account_id: Optional[str] = Field(
        None,
        description="Specific account ID to target. If omitted, FIFO selection is used."
    )

class TaskResponse(BaseModel):
    status: str
    message: str
    account_id: Optional[str] = None
    order_reference: Optional[str] = None
    dispatched_at: str

# Background Automation Pipeline
async def execute_task_pipeline(
    record_id: str,
    account_data: dict,
    target_contact: str,
    sender_filter: str,
) -> None:
    supabase = get_supabase_client()
    logger.info(f"[PIPELINE:START] Beginning pipeline for record ID: {record_id}")

    try:
        # 1. حجز الحساب أثناء المعالجة
        supabase.table("stock_accounts").update({
            "status": "reserved",
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", record_id).execute()

        runner = AutomationRunner()
        task_payload = {
            "account_id": record_id,
            "account_identifier": account_data.get("steam_username"),
            "account_secret": account_data.get("steam_password"),
            "original_email": account_data.get("original_email"),
            "email_password": account_data.get("email_password"),
            "target_contact": target_contact
        }

        # 2. تشغيل الأتمتة بالمتصفح
        await runner.execute_task(TARGET_DASHBOARD_URL, task_payload)

        # 3. اكتمال العملية بنجاح
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
            logger.error(f"[SUPABASE:FAIL] Could not reset account status: {update_err}")
    finally:
        if 'runner' in locals():
            await runner.close()

# API Endpoints
@app.post("/api/process-task", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def process_task(payload: ProcessTaskRequest, background_tasks: BackgroundTasks):
    try:
        supabase = get_supabase_client()

        query = supabase.table("stock_accounts").select(
            "id, steam_username, steam_password, original_email, email_password, status"
        ).eq("status", "available")

        if payload.account_id:
            logger.info(f"[DISPATCH] Specific account requested: {payload.account_id}")
            query_result = query.eq("id", payload.account_id).execute()
        else:
            logger.info("[DISPATCH] No specific account requested. Fetching oldest available.")
            query_result = query.order("created_at", desc=False).limit(1).execute()

        records = query_result.data
        if not records:
            logger.warning("[DISPATCH] No available accounts found in Supabase stock_accounts table.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No stock accounts currently available with status 'available'."
            )

        target_record = records[0]
        record_id = target_record["id"]
        logger.info(f"[DISPATCH] Assigning record {record_id} ({target_record.get('steam_username')})")

        background_tasks.add_task(
            execute_task_pipeline,
            record_id=record_id,
            account_data=target_record,
            target_contact=payload.target_contact,
            sender_filter=payload.sender_filter
        )

        return TaskResponse(
            status="queued",
            message="Task queued successfully for background execution.",
            account_id=record_id,
            order_reference=payload.order_reference,
            dispatched_at=datetime.utcnow().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[DISPATCH:FAIL] Database error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database configuration error: {str(e)}"
        )

@app.get("/healthz", tags=["Monitoring"])
async def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
