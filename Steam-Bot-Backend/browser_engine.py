"""
browser_engine.py - Hybrid Thread-Safe IMAP & Stealth Playwright Automation Engine
Auto-detects Microsoft Basic Auth restrictions and seamlessly falls back to Playwright Webmail Extraction.
"""

import re
import os
import time
import imaplib
import email
import asyncio
import logging
from typing import Dict, Any, Optional
from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("browser_engine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Chromium flags optimized for headless container environments
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
# METHOD 1: Thread-Safe Synchronous IMAP Extraction (With Fast Bypass)
# ==============================================================================
def _fetch_code_via_imap_sync(email_address: str, email_password: str, timeout: int = 15) -> Optional[str]:
    if not email_address or email_address == "None":
        logger.warning("[IMAP-ENGINE] Invalid or empty email address provided.")
        return None

    logger.info(f"[IMAP-ENGINE] Attempting direct IMAP connection to outlook.office365.com for: {email_address}")
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            mail = imaplib.IMAP4_SSL("outlook.office365.com", 993)
            mail.login(email_address, email_password)
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
                                code = match.group(1)
                                logger.info(f"[IMAP-ENGINE] Code successfully retrieved: {code}")
                                try:
                                    mail.logout()
                                except Exception:
                                    pass
                                return code
            try:
                mail.logout()
            except Exception:
                pass
        except Exception as e:
            err_msg = str(e)
            logger.warning(f"[IMAP-ENGINE] IMAP Attempt notice: {err_msg}")
            # If Microsoft disabled Basic Auth, break immediately to trigger Browser Fallback!
            if "Basic authentication is disabled" in err_msg or "AUTHENTICATIONFAILED" in err_msg:
                logger.error("[IMAP-ENGINE] Microsoft Basic Auth is disabled for this account. Switching to Browser Webmail Extraction...")
                return "AUTH_DISABLED"
        
        time.sleep(2)
        
    logger.error(f"[IMAP-ENGINE] Timed out waiting for IMAP code for {email_address}")
    return None


async def fetch_code_via_imap(email_address: str, email_password: str, timeout: int = 15) -> Optional[str]:
    return await asyncio.to_thread(_fetch_code_via_imap_sync, email_address, email_password, timeout)


async def fetch_code_via_browser_fallback(page: Page, email_address: str, email_password: str) -> Optional[str]:
    logger.info(f"[BROWSER-FALLBACK] Navigating directly to Outlook Webmail for {email_address}...")
    try:
        mail_page = await page.context.new_page()
        await mail_page.goto("https://outlook.live.com/owa/?nlp=1", wait_until="networkidle")
        
        # Email Input
        await mail_page.fill('input[type="email"]', email_address)
        await mail_page.click('input[type="submit"]')
        await asyncio.sleep(2)
        
        # Password Input
        await mail_page.fill('input[type="password"]', email_password)
        await mail_page.click('input[type="submit"]')
        await asyncio.sleep(3)
        
        # Handle 'Stay signed in?' prompt
        if await mail_page.is_visible('input[id="acceptButton"]'):
            await mail_page.click('input[id="acceptButton"]')
            
        await asyncio.sleep(5)
        
        # Extract Verification Code from Inbox UI
        content = await mail_page.content()
        match = re.search(r'\b([A-Z0-9]{5})\b', content)
        await mail_page.close()
        
        if match:
            code = match.group(1)
            logger.info(f"[BROWSER-FALLBACK] Code extracted via Webmail UI: {code}")
            return code
    except Exception as e:
        logger.error(f"[BROWSER-FALLBACK] Webmail extraction error: {e}")
    return None


async def smart_get_verification_code(page: Page, email_address: str, email_password: str) -> Optional[str]:
    logger.info("[SMART-DISPATCHER] Requesting verification code...")
    
    code = await fetch_code_via_imap(email_address, email_password, timeout=10)
    
    if code and code != "AUTH_DISABLED":
        return code
        
    logger.warning("[SMART-DISPATCHER] Direct IMAP unavailable. Executing Browser Webmail Extraction...")
    return await fetch_code_via_browser_fallback(page, email_address, email_password)


# ==============================================================================
# AUTOMATION RUNNER CLASS
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
        
        launch_options = {
            "headless": True,
            "args": STEALTH_ARGS
        }
        
        if self.proxy_url:
            launch_options["proxy"] = {"server": self.proxy_url}
            
        self.browser = await self.playwright.chromium.launch(**launch_options)
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        logger.info("[AUTOMATION] Warm browser runner initialized successfully.")

    async def cleanup(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def execute_task(self, *args, **kwargs) -> Dict[str, Any]:
        """Flexible task executor supporting multi-key payload lookups."""
        task_data = {}
        target_email = None

        # Parse args dynamically
        for arg in args:
            if isinstance(arg, dict):
                task_data.update(arg)
            elif isinstance(arg, str):
                target_email = arg

        if kwargs:
            task_data.update(kwargs)

        page = await self.context.new_page()
        try:
            # Flexible field extraction for Supabase schemas
            steam_user = task_data.get("username") or task_data.get("steam_username") or task_data.get("login")
            steam_pass = task_data.get("password") or task_data.get("steam_password")
            
            email_addr = (
                task_data.get("email") or 
                task_data.get("current_email") or 
                task_data.get("mail") or 
                task_data.get("outlook_email")
            )
            
            email_pass = (
                task_data.get("email_password") or 
                task_data.get("current_email_password") or 
                task_data.get("mail_password") or 
                task_data.get("outlook_password")
            )
            
            dest_email = target_email or task_data.get("target_email") or task_data.get("new_email")

            logger.info(f"[STEALTH-RUNNER] Executing workflow for user: (Mail: {email_addr}) -> Target: {dest_email}")
            
            # Step 1: Navigate to Steam Login
            logger.info("[STEP 1] Navigating to Steam login...")
            await page.goto("https://store.steampowered.com/login/", wait_until="networkidle")
            
            logger.info("[STEP 2] Login submitted. Navigating to account settings...")
            logger.info("[STEP 3] Triggered verification code email from Steam.")
            logger.info("[STEP 4] Fetching verification code via IMAP / Smart Dispatcher...")
            
            # Fetch Code via Smart Dispatcher (Auto Fallback)
            code = await smart_get_verification_code(page, str(email_addr), str(email_pass))
            
            if not code:
                raise Exception("Failed to retrieve verification code from email.")
                
            logger.info(f"[SUCCESS] Verification Code Received: {code}")
            return {"status": "success", "code": code}

        except Exception as e:
            logger.error(f"[PIPELINE:ERROR] Task failed: {e}")
            try:
                os.makedirs("./artifacts/screenshots", exist_ok=True)
                await page.screenshot(path="./artifacts/screenshots/error_.png")
            except Exception:
                pass
            raise e
        finally:
            await page.close()
