import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from supabase import create_client

from browser_engine import AutomationRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("orchestrator.main")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

runner = AutomationRunner()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # تشغيل المتصفح فور إقلاع السيرفر ليكون Warm وجاهز فوراً
    logger.info("[STARTUP] Initializing Warm Browser Instance...")
    await runner.initialize()
    yield
    # إغلاق المتصفح عند إيقاف السيرفر
    logger.info("[SHUTDOWN] Closing Browser Instance...")
    await runner.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TaskPayload(BaseModel):
    account_id: Optional[str] = None
    target_contact: Optional[str] = "abutrabali4@gmail.com"

async def background_pipeline(account_id: str, new_email: str):
    try:
        res = supabase.table("stock_accounts").select("*").eq("id", account_id).execute()
        if not res.data:
            logger.error(f"[PIPELINE:ERROR] Account {account_id} not found.")
            return

        acc = res.data[0]
        supabase.table("stock_accounts").update({"status": "reserved"}).eq("id", account_id).execute()

        payload = {
            "account_id": acc["id"],
            "account_identifier": acc.get("steam_username"),
            "account_secret": acc.get("steam_password"),
            "original_email": acc.get("original_email"),
            "email_password": acc.get("email_password"),
            "target_contact": new_email
        }

        await runner.execute_task("", payload)
        supabase.table("stock_accounts").update({"status": "used"}).eq("id", account_id).execute()

    except Exception as e:
        logger.error(f"[PIPELINE:ERROR] Task failed for record {account_id}: {str(e)}")
        if supabase:
            supabase.table("stock_accounts").update({"status": "available"}).eq("id", account_id).execute()

@app.post("/api/process-task")
async def process_task(payload: TaskPayload, bg_tasks: BackgroundTasks):
    account_id = payload.account_id
    if not account_id:
        res = supabase.table("stock_accounts").select("id").eq("status", "available").order("created_at").limit(1).execute()
        if not res.data:
            logger.warning("[DISPATCH] No available accounts found in Supabase stock_accounts table.")
            raise HTTPException(status_code=404, detail="No available accounts found")
        account_id = res.data[0]["id"]

    bg_tasks.add_task(background_pipeline, account_id, payload.target_contact)
    return {"status": "accepted", "account_id": account_id}
