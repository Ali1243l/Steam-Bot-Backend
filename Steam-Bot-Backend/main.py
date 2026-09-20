"""
main.py - FastAPI Application Server & Task Dispatcher
Full Supabase synchronization & robust headers handling.
"""

import os
import logging
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any

from browser_engine import AutomationRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("main")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://mgddwvkgswdahragsazv.supabase.co")
SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY") or 
    os.getenv("SUPABASE_ANON_KEY") or 
    os.getenv("SUPABASE_KEY") or 
    ""
).strip()

def get_supabase_headers() -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    if SUPABASE_KEY:
        headers["apikey"] = SUPABASE_KEY
        headers["Authorization"] = f"Bearer {SUPABASE_KEY}"
    return headers

runner = AutomationRunner()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await runner.initialize()
    yield
    await runner.cleanup()

app = FastAPI(title="Steam Automation API", lifespan=lifespan)

async def process_account_task(record_id: str, target_email: Optional[str] = None):
    headers = get_supabase_headers()
    
    async with httpx.AsyncClient() as client:
        # 1. Fetch full record details from Supabase
        res = await client.get(f"{SUPABASE_URL}/rest/v1/stock_accounts?id=eq.{record_id}", headers=headers)
        if res.status_code != 200 or not res.json():
            logger.error(f"Failed to fetch record {record_id} from Supabase. Status: {res.status_code}")
            return

        record = res.json()[0]
        logger.info(f"[SUPABASE-RECORD-FETCHED] Record ID: {record_id} | Keys: {list(record.keys())}")
        
        if target_email:
            record["target_email"] = target_email

        # 2. Update status to 'processing'
        await client.patch(
            f"{SUPABASE_URL}/rest/v1/stock_accounts?id=eq.{record_id}",
            json={"status": "processing"},
            headers=headers
        )

        try:
            # 3. Execute Automation Task
            result = await runner.execute_task(record)
            
            # 4. Mark completed in Supabase
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/stock_accounts?id=eq.{record_id}",
                json={"status": "completed", "notes": f"Code: {result.get('code')}"},
                headers=headers
            )
            logger.info(f"[TASK-SUCCESS] Record {record_id} completed successfully.")
        except Exception as e:
            logger.error(f"[TASK-FAILED] Record {record_id} failed: {e}")
            await client.patch(
                f"{SUPABASE_URL}/rest/v1/stock_accounts?id=eq.{record_id}",
                json={"status": "failed", "notes": str(e)},
                headers=headers
            )

@app.get("/")
def read_root():
    return {"status": "online", "service": "Steam Automation Engine"}

@app.get("/openapi.json")
def get_openapi():
    return app.openapi()

@app.post("/api/process-task")
async def trigger_task(background_tasks: BackgroundTasks, payload: Optional[Dict[str, Any]] = None):
    headers = get_supabase_headers()
    
    async with httpx.AsyncClient() as client:
        # Fetch available account
        res = await client.get(
            f"{SUPABASE_URL}/rest/v1/stock_accounts?status=eq.available&order=created_at.asc&limit=1",
            headers=headers
        )
        if res.status_code != 200:
            logger.error(f"Supabase request failed with status {res.status_code}: {res.text}")
            raise HTTPException(status_code=500, detail=f"Supabase connection error: {res.status_code}")
            
        data = res.json()
        if not data:
            raise HTTPException(status_code=444, detail="No available accounts found")

        record_id = data[0]["id"]
        target_email = payload.get("target_email") if payload else None
        
        background_tasks.add_task(process_account_task, record_id, target_email)
        return {"status": "queued", "record_id": record_id}
