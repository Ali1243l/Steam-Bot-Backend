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

@app.get("/")
@app.get("/api/health")
@app.get("/api/logs")
@app.get("/api/bot/api/health")
def health_and_logs():
    return {
        "status": "online",
        "healthy": True,
        "server": "Steam Automation AWS Engine",
        "logs": live_activity_logs[-80:],
        "active_session": bool(active_session and active_session.page),
        "timestamp": datetime.datetime.now().isoformat()
    }

@app.get("/api/latest-screenshot")
@app.get("/api/screenshot")
@app.get("/screenshot")
def get_latest_screenshot():
    latest_img = os.path.join(SCREENSHOTS_DIR, "latest.png")
    if os.path.exists(latest_img):
        return FileResponse(latest_img, media_type="image/png")
    return Response(status_code=204)

def run_email_change_worker(account: dict, target_email: str):
    global active_session, active_account_context
    account_id = account.get("id")
    add_log(f"[WORKER] Starting headless pipeline for Steam user: {account.get('steam_username')} -> {target_email}")
    
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
        add_log(f"[ALLOCATED] Allocated account from Supabase stock: {account.get('steam_username')}")

    background_tasks.add_task(run_email_change_worker, account, target_email)

    return {
        "success": True,
        "status": "processing",
        "message": f"Task queued and executing in background for {target_email}",
        "allocated_username": account.get("steam_username")
    }

@app.post("/api/finalize-email-change")
@app.post("/api/bot/api/finalize-email-change")
def finalize_email_change(req: FinalizeCodeRequest):
    global active_session, active_account_context
    code = req.code.strip().upper()
    add_log(f"[FINALIZE_REQUEST] Received final code [{code}] for {req.target_email}")

    if not active_session or not active_session.page:
        add_log("[FINALIZE_ERROR] No active Playwright session in progress.", "error")
        account_id = active_account_context.get("account_id")
        if account_id:
            update_account_status(account_id, "completed", {"target_verification_code": code})
        return {"success": True, "warning": "Code recorded in Supabase."}

    res = active_session.submit_final_verification_code(code)
    account_id = active_account_context.get("account_id")
    if res.get("success"):
        if account_id:
            update_account_status(account_id, "completed", {"target_verification_code": code})
        add_log(f"[COMPLETED] Email change successfully finalized for {req.target_email}!")
        return {"success": True, "message": "Email changed successfully!"}
    else:
        if account_id:
            update_account_status(account_id, "failed", {"last_error": res.get("error")})
        raise HTTPException(status_code=500, detail=res.get("error"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
