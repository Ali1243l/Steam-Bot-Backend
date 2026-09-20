"""
browser_engine.py - Production Ready Engine
Mapped precisely to Supabase schema keys: original_email, steam_username, email_password.
"""

import re
import os
import time
import imaplib
import email
import asyncio
import logging
from typing import Dict, Any, Optional
from playwright.async_api import async_playwright, BrowserContext, Page

logger = logging.getLogger("browser_engine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

STEALTH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-accelerated-2d-canvas",
    "--no-first-run",
    "--no-zygote",
    "--single-process",
    "--disable-gpu",
    "--disable-extensions",
]

def _fetch_code_via_imap_sync(email_addr: str, email_pass: str, timeout: int = 10) -> Optional[str]:
    if not email_addr or email_addr == "None":
        return None

    try:
        mail = imaplib.IMAP4_SSL("outlook.office365.com", 993)
        mail.login(email_addr, email_pass)
        mail.select("INBOX")
        status, messages = mail.search(None, '(FROM "noreply@steampowered.com")')
        if status == "OK" and messages[0]:
            email_ids = messages[0].split()
            for e_id in reversed(email_ids[-3:]):
                status, msg_data = mail.fetch(e_id, "(RFC822)")
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        subject = str(msg.get("subject", ""))
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    body += part.get_payload(decode=True).decode(errors="ignore")
                        else:
                            body = msg.get_payload(decode=True).decode(errors="ignore")

                        match = re.search(r'\b([A-Z0-9]{5})\b', body) or re.search(r'\b([A-Z0-9]{5})\b', subject)
                        if match:
                            mail.logout()
                            return match.group(1)
        mail.logout()
    except Exception as e:
        if "Basic authentication is disabled" in str(e):
            return "AUTH_DISABLED"
    return None

async def fetch_code_via_browser(page: Page, email_addr: str, email_pass: str) -> Optional[str]:
    logger.info(f"[WEBMAIL-EXTRACTOR] Opening Outlook for: {email_addr}")
    try:
        mail_page = await page.context.new_page()
        await mail_page.goto("https://outlook.live.com/owa/?nlp=1", wait_until="networkidle")
        
        await mail_page.fill('input[type="email"]', email_addr)
        await mail_page.click('input[type="submit"]')
        await asyncio.sleep(2)
        
        await mail_page.fill('input[type="password"]', email_pass)
        await mail_page.click('input[type="submit"]')
        await asyncio.sleep(3)
        
        if await mail_page.is_visible('input[id="acceptButton"]'):
            await mail_page.click('input[id="acceptButton"]')
            
        await asyncio.sleep(5)
        content = await mail_page.content()
        match = re.search(r'\b([A-Z0-9]{5})\b', content)
        await mail_page.close()
        if match:
            return match.group(1)
    except Exception as e:
        logger.error(f"[WEBMAIL-EXTRACTOR] Error: {e}")
    return None

async def get_steam_code(page: Page, email_addr: str, email_pass: str) -> Optional[str]:
    code = await asyncio.to_thread(_fetch_code_via_imap_sync, email_addr, email_pass, 10)
    if code and code != "AUTH_DISABLED":
        return code
        
    logger.warning("[SMART-DISPATCHER] IMAP restricted by Microsoft. Switching to Playwright Webmail...")
    return await fetch_code_via_browser(page, email_addr, email_pass)

class AutomationRunner:
    def __init__(self, proxy_url: Optional[str] = None):
        self.playwright = None
        self.browser = None
        self.context = None
        self.proxy_url = proxy_url

    async def initialize(self):
        logger.info("[STARTUP] Initializing Warm Browser Instance...")
        self.playwright = await async_playwright().start()
        launch_opts = {"headless": True, "args": STEALTH_ARGS}
        if self.proxy_url:
            launch_opts["proxy"] = {"server": self.proxy_url}
            
        self.browser = await self.playwright.chromium.launch(**launch_opts)
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        logger.info("[AUTOMATION] Warm browser initialized.")

    async def cleanup(self):
        if self.context: await self.context.close()
        if self.browser: await self.browser.close()
        if self.playwright: await self.playwright.stop()

    async def execute_task(self, *args, **kwargs) -> Dict[str, Any]:
        payload = {}
        for arg in args:
            if isinstance(arg, dict): payload.update(arg)
        if kwargs: payload.update(kwargs)

        # Mapped specifically to Supabase Schema
        steam_user = payload.get("steam_username") or payload.get("username")
        steam_pass = payload.get("steam_password") or payload.get("password")
        
        email_addr = (
            payload.get("original_email") or 
            payload.get("email") or 
            payload.get("current_email")
        )
        email_pass = (
            payload.get("email_password") or 
            payload.get("current_email_password")
        )
        target_email = payload.get("target_email") or payload.get("new_email")

        logger.info(f"[TASK-DATA] Username: {steam_user} | Original Email: {email_addr} | Target: {target_email}")

        if not email_addr or str(email_addr).strip() == "None":
            raise ValueError(f"ERR_MISSING_EMAIL: Email data is empty in payload. Received keys: {list(payload.keys())}")

        page = await self.context.new_page()
        try:
            logger.info("[STEP 1] Navigating to Steam login...")
            await page.goto("https://store.steampowered.com/login/", wait_until="networkidle")
            
            logger.info("[STEP 2] Fetching verification code...")
            code = await get_steam_code(page, str(email_addr), str(email_pass))
            
            if not code:
                raise Exception("Failed to retrieve verification code from email.")
                
            logger.info(f"[SUCCESS] Code extracted: {code}")
            return {"status": "success", "code": code}
        except Exception as e:
            logger.error(f"[PIPELINE-ERROR] {e}")
            try:
                os.makedirs("./artifacts/screenshots", exist_ok=True)
                await page.screenshot(path="./artifacts/screenshots/error_.png")
            except Exception: pass
            raise e
        finally:
            await page.close()
