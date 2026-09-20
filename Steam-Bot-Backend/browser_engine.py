"""
browser_engine.py - Full Production Playwright Automation Engine
Executes real DOM interaction with Steam Login and Microsoft Outlook Webmail.
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

# ==============================================================================
# 1. IMAP & REAL WEBMAIL CODE EXTRACTORS
# ==============================================================================
def _fetch_code_via_imap_sync(email_addr: str, email_pass: str, timeout: int = 8) -> Optional[str]:
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
    logger.info(f"[WEBMAIL-EXTRACTOR] Navigating live browser to Outlook for: {email_addr}")
    try:
        mail_page = await page.context.new_page()
        await mail_page.goto("https://login.live.com/", wait_until="networkidle")
        
        # Fill Microsoft Login (Supports name="loginfmt", id="i0116", or type="email")
        email_selector = 'input[name="loginfmt"], input[type="email"], #i0116'
        await mail_page.wait_for_selector(email_selector, timeout=10000)
        await mail_page.fill(email_selector, email_addr)
        await mail_page.click('input[type="submit"], #idSIButton9')
        await asyncio.sleep(2)
        
        # Fill Password
        pass_selector = 'input[name="passwd"], input[type="password"], #i0118'
        await mail_page.wait_for_selector(pass_selector, timeout=10000)
        await mail_page.fill(pass_selector, email_pass)
        await mail_page.click('input[type="submit"], #idSIButton9')
        await asyncio.sleep(3)
        
        # Dismiss 'Stay signed in?' prompt if appears
        if await mail_page.is_visible('input[id="acceptButton"]'):
            await mail_page.click('input[id="acceptButton"]')
            
        await asyncio.sleep(4)
        
        # Navigate to inbox
        await mail_page.goto("https://outlook.live.com/mail/0/", wait_until="networkidle")
        await asyncio.sleep(5)
        
        content = await mail_page.content()
        match = re.search(r'\b([A-Z0-9]{5})\b', content)
        await mail_page.close()
        if match:
            return match.group(1)
    except Exception as e:
        logger.error(f"[WEBMAIL-EXTRACTOR] Webmail DOM Error: {e}")
    return None

async def get_steam_code(page: Page, email_addr: str, email_pass: str) -> Optional[str]:
    code = await asyncio.to_thread(_fetch_code_via_imap_sync, email_addr, email_pass, 8)
    if code and code != "AUTH_DISABLED":
        return code
        
    logger.warning("[SMART-DISPATCHER] Direct IMAP restricted. Launching live Outlook webmail interaction...")
    return await fetch_code_via_browser(page, email_addr, email_pass)

# ==============================================================================
# 2. REAL AUTOMATION RUNNER CLASS
# ==============================================================================
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

        logger.info(f"[TASK-EXECUTION] Logging into Steam: {steam_user} | Mail: {email_addr}")

        if not email_addr or str(email_addr).strip() == "None":
            raise ValueError("ERR_MISSING_EMAIL: Email field is empty.")

        page = await self.context.new_page()
        try:
            # Step 1: Open Steam Login Page
            logger.info("[STEP 1] Opening Steam login page...")
            await page.goto("https://store.steampowered.com/login/", wait_until="networkidle")
            await asyncio.sleep(2)

            # Step 2: Fill Steam Username and Password on UI
            logger.info("[STEP 2] Submitting Steam credentials to DOM...")
            
            # Select inputs on Steam modern React UI
            inputs = await page.query_selector_all('input[type="text"], input[type="password"]')
            if len(inputs) >= 2:
                await inputs[0].fill(str(steam_user))
                await inputs[1].fill(str(steam_pass))
            else:
                # Fallback selectors
                await page.fill('input[type="text"]', str(steam_user))
                await page.fill('input[type="password"]', str(steam_pass))

            # Click Sign In button
            await page.click('button[type="submit"]')
            logger.info("[STEP 3] Login submitted to Steam. Waiting for Steam Guard email dispatch...")
            await asyncio.sleep(5)

            # Step 4: Fetch Verification Code from Email
            logger.info("[STEP 4] Fetching Steam Guard code...")
            code = await get_steam_code(page, str(email_addr), str(email_pass))
            
            if not code:
                raise Exception("Failed to retrieve verification code from email.")
                
            logger.info(f"[STEP 5] Verification Code Extracted Successfully: {code}")

            # Step 5: Input Verification Code into Steam Guard UI Prompt
            guard_input = await page.wait_for_selector('input[type="text"]', timeout=10000)
            if guard_input:
                await guard_input.fill(code)
                logger.info("[STEP 6] Code entered into Steam Guard input prompt!")

            await page.screenshot(path="./artifacts/screenshots/login_success.png")
            return {"status": "success", "code": code}

        except Exception as e:
            logger.error(f"[PIPELINE-ERROR] Task execution failed: {e}")
            try:
                os.makedirs("./artifacts/screenshots", exist_ok=True)
                await page.screenshot(path="./artifacts/screenshots/error_.png")
            except Exception: pass
            raise e
        finally:
            await page.close()
