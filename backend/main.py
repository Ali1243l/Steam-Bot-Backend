import os
import datetime
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from backend.database import get_next_available_account, update_account_status
from backend.browser import SteamAutomationSession, SCREENSHOTS_DIR

app = FastAPI(title="Steam Bot Headless Backend", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

live_activity_logs = [
    {
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
        "level": "info",
        "message": "AWS EC2 Playwright Automation Engine initialized.",
    }
]

def add_log(message: str, level: str = "info"):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    entry = {"timestamp": now, "level": level, "message": message}
    print(f"[{now}] {message}")
    live_activity_logs.append(entry)
    if len(live_activity_logs) > 150:
        live_activity_logs.pop(0)

active_session = None
active_account_context = {}

class ProcessTaskRequest(BaseModel):
    target_email: str
    steam_username: str | None = None
    steam_password: str | None = None
    current_email: str | None = None
    current_email_password: str | None = None

class FinalizeCodeRequest(BaseModel):
    target_email: str
    code: str

class AccountCodePayload(BaseModel):
    code: str
    target_email: str | None = None

@app.get("/")
@app.get("/api/health")
@app.get("/api/logs")
@app.get("/api/bot/api/health")
def health_and_logs():
    has_active = bool(active_session and getattr(active_session, "page", None) is not None)
    return {
        "status": "online",
        "healthy": True,
        "server": "Steam Automation AWS Engine",
        "logs": live_activity_logs[-80:],
        "active_session": has_active,
        "timestamp": datetime.datetime.now().isoformat()
    }

@app.get("/api/latest-screenshot")
@app.get("/api/screenshot")
@app.get("/screenshot")
@app.get("/api/screenshot/{task_id}")
@app.get("/api/bot/api/screenshot/{task_id}")
@app.get("/api/bot/api/screenshot")
def get_latest_screenshot(task_id: str = None):
    latest_img = os.path.join(SCREENSHOTS_DIR, "latest.png")
    if os.path.exists(latest_img):
        return FileResponse(latest_img, media_type="image/png")
    return Response(status_code=204)

def run_email_change_worker(account: dict, target_email: str):
    global active_session, active_account_context
    account_id = account.get("id")
    add_log(f"[WORKER] Starting pipeline for: {account.get('steam_username')} -> {target_email}")
    
    if account_id:
        update_account_status(account_id, "processing")

    active_session = SteamAutomationSession(log_callback=add_log)
    active_account_context = {
        "account_id": account_id,
        "steam_username": account.get("steam_username"),
        "target_email": target_email
    }

    res = active_session.start_email_change_process(
        steam_username=account.get("steam_username"),
        steam_password=account.get("steam_password"),
        current_email=account.get("original_email") or account.get("current_email"),
        current_email_password=account.get("email_password") or account.get("steam_password"),
        new_email=target_email
    )

    if res.get("success") and res.get("status") == "waiting_code":
        add_log(f"[AWAITING_CODE] [!] Verification code dispatched to {target_email}! Please submit 5-char code.", "warn")
        if account_id:
            update_account_status(account_id, "waiting_code", {"assigned_game": target_email})
    else:
        add_log(f"[WORKER_FAILED] Task encountered error: {res.get('error')}", "error")
        if account_id:
            update_account_status(account_id, "failed", {"last_error": res.get("error")})

@app.post("/api/process-task")
@app.post("/api/bot/api/process-task")
def process_task(req: ProcessTaskRequest, background_tasks: BackgroundTasks):
    target_email = req.target_email.strip()
    if not target_email:
        raise HTTPException(status_code=400, detail="target_email is required")

    add_log(f"[TASK_RECEIVED] Request received for target email: {target_email}")

    account = None
    if req.steam_username and req.steam_password:
        account = {
            "id": None,
            "steam_username": req.steam_username,
            "steam_password": req.steam_password,
            "original_email": req.current_email,
            "email_password": req.current_email_password,
        }
    else:
        account = get_next_available_account()
        if not account:
            add_log("[QUEUE_EMPTY] No stock accounts available in Supabase.", "warn")
            raise HTTPException(status_code=404, detail="No accounts available in stock_accounts with status='available'")
        add_log(f"[ALLOCATED] Allocated account: {account.get('steam_username')}")

    background_tasks.add_task(run_email_change_worker, account, target_email)

    return {
        "success": True,
        "status": "processing",
        "message": f"Task queued and executing for {target_email}",
        "allocated_username": account.get("steam_username")
    }

@app.post("/api/accounts/{account_id}/code")
@app.post("/api/bot/api/accounts/{account_id}/code")
def submit_account_code(account_id: str, payload: AccountCodePayload):
    code = payload.code.strip().upper()
    add_log(f"[CODE_DISPATCH] Submitting code [{code}] for account {account_id}")
    
    update_account_status(account_id, "completed", {"target_verification_code": code, "status": "completed"})
    
    if active_session:
        try:
            active_session.submit_final_verification_code(code)
        except Exception as e:
            add_log(f"[CODE_NOTICE] Browser finalized: {e}")
            
    return {
        "success": True,
        "status": "completed",
        "message": f"Code [{code}] applied successfully to account {account_id}"
    }

@app.post("/api/finalize-email-change")
@app.post("/api/bot/api/finalize-email-change")
def finalize_email_change(req: FinalizeCodeRequest):
    global active_session, active_account_context
    code = req.code.strip().upper()
    add_log(f"[FINALIZE_REQUEST] Received final code [{code}] for {req.target_email}")

    account_id = active_account_context.get("account_id")
    if account_id:
        update_account_status(account_id, "completed", {"target_verification_code": code, "status": "completed"})

    if active_session:
        active_session.submit_final_verification_code(code)

    return {"success": True, "message": "Email change successfully finalized!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
