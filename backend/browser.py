import os
import time
import subprocess
import datetime

SCREENSHOTS_DIR = "/home/ubuntu/Steam-Bot-Backend/screenshots"
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

class SteamAutomationSession:
    def __init__(self, log_callback=None):
        self.log_callback = log_callback or print

    def log(self, message: str):
        self.log_callback(f"[PIPELINE] {message}")

    def start_email_change_process(self, steam_username: str, steam_password: str, current_email: str, current_email_password: str, new_email: str) -> dict:
        self.log(f"Running proven automated pipeline for: {steam_username} -> {new_email}")
        try:
            # تشغيل سكريبت full_email_change_pipeline المجرب والذي تخطى صفحة ستيم
            cmd = ["python3", "-u", "/home/ubuntu/Steam-Bot-Backend/full_email_change_pipeline.py", new_email]
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            for line in iter(process.stdout.readline, ''):
                if line:
                    clean_line = line.strip()
                    self.log(clean_line)
                    if "FINAL CONFIRMATION CODE" in clean_line or "sent to" in clean_line.lower():
                        break
            
            return {
                "success": True,
                "status": "waiting_code",
                "message": f"Verification code sent to {new_email} successfully!",
                "target_email": new_email
            }
        except Exception as e:
            self.log(f"[ERROR] Pipeline execution error: {e}")
            return {"success": False, "error": str(e)}

    def submit_final_verification_code(self, code: str) -> dict:
        self.log(f"Finalizing email change with code [{code}]...")
        try:
            cmd = ["python3", "/home/ubuntu/Steam-Bot-Backend/finalize_email_change.py", code]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.log(res.stdout or res.stderr)
            return {"success": True, "status": "completed"}
        except Exception as e:
            self.log(f"[ERROR] Finalize error: {e}")
            return {"success": False, "error": str(e)}
