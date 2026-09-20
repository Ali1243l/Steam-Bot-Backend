"""
main.py - FastAPI Application Server & Task Dispatcher
Resolves HTTP 401 Unauthorized by dynamically parsing Supabase Keys from payload/headers/env.
"""

import os
import logging
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any

from browser_engine import AutomationRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("main")

DEFAULT_SUPABASE_URL = os.getenv("SUPABASE_URL", "https://mgddwvkgswdahragsazv.supabase.co")
DEFAULT_SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY") or 
    os.getenv("SUPABASE_ANON_KEY") or 
    os.getenv("SUPABASE_KEY") or 
    ""
).strip()

def build_supabase_headers(custom_key: Optional[str] = None) -> Dict[str, str]:
    key = (custom_key or DEFAULT_SUPABASE_KEY).strip()
    headers = {
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    if key:
        headers["apikey"] = key
        headers["Authorization"] = f"Bearer {key}"
    return headers

runner = AutomationRunner()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await runner.initialize()
    yield
    await runner.cleanup()

app = FastAPI(title="Steam Automation API", lifespan=lifespan)

async def process_account_task(record_id: str, target_email: Optional[str] = None, custom_key: Optional[str] = None):
    headers = build_supabase_headers(custom_key)
    
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{DEFAULT_SUPABASE_URL}/rest/v1/stock_accounts?id=eq.{record_id}", headers=headers)
        if res.status_code != 200 or not res.json():
            logger.error(f"[SUPABASE-ERR] Fetch record {record_id} failed with HTTP {res.status_code}: {res.text}")
            return

        record = res.json()[0]
        if target_email:
            record["target_email"] = target_email

        await client.patch(
            f"{DEFAULT_SUPABASE_URL}/rest/v1/stock_accounts?id=eq.{record_id}",
            json={"status": "processing"},
            headers=headers
        )

        try:
            result = await runner.execute_task(record)
            await client.patch(
                f"{DEFAULT_SUPABASE_URL}/rest/v1/stock_accounts?id=eq.{record_id}",
                json={"status": "completed", "notes": f"Code: {result.get('code')}"},
                headers=headers
            )
            logger.info(f"[TASK-SUCCESS] Record {record_id} completed successfully.")
        except Exception as e:
            logger.error(f"[TASK-FAILED] Record {record_id} failed: {e}")
            await client.patch(
                f"{DEFAULT_SUPABASE_URL}/rest/v1/stock_accounts?id=eq.{record_id}",
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
async def trigger_task(request: Request, background_tasks: BackgroundTasks, payload: Optional[Dict[str, Any]] = None):
    payload = payload or {}
    
    # Dynamically resolve Supabase Key from headers, payload, or env
    header_key = request.headers.get("apikey") or request.headers.get("x-supabase-key") or request.headers.get("authorization")
    if header_key and header_key.startswith("Bearer "):
        header_key = header_key.replace("Bearer ", "").strip()
        
    custom_key = header_key or payload.get("supabase_key") or payload.get("apikey") or DEFAULT_SUPABASE_KEY
    
    headers = build_supabase_headers(custom_key)
    
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{DEFAULT_SUPABASE_URL}/rest/v1/stock_accounts?status=eq.available&order=created_at.asc&limit=1",
            headers=headers
        )
        
        if res.status_code == 401:
            logger.error("[SUPABASE-401] Supabase rejected request: Unauthorized. Check ANON/SERVICE KEY.")
            raise HTTPException(status_code=401, detail="Supabase connection error: 401 (Missing or Invalid Supabase API Key)")
            
        if res.status_code != 200:
            logger.error(f"[SUPABASE-ERR] Supabase status {res.status_code}: {res.text}")
            raise HTTPException(status_code=res.status_code, detail=f"Supabase error {res.status_code}")
            
        data = res.json()
        if not data:
            raise HTTPException(status_code=444, detail="No available accounts found")

        record_id = data[0]["id"]
        target_email = payload.get("target_email")
        
        background_tasks.add_task(process_account_task, record_id, target_email, custom_key)
        return {"status": "queued", "record_id": record_id}
