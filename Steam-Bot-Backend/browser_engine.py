"""
browser_engine.py - Hybrid IMAP & Stealth Playwright Automation Engine
"""

import re
import os
import imaplib
import email
from email.header import decode_header
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


# ============================================================================
# METHOD 1: Direct Python IMAP Extraction (Primary)
# ============================================================================
def fetch_code_via_imap(email_address: str, password: str, timeout_seconds: int = 45) -> Optional[str]:
    """
    Connects directly to outlook.office365.com via IMAP over SSL (Port 993),
    searches recent inbox messages, and extracts the 5-character Steam verification code.
    """
    logger.info(f"[IMAP-ENGINE] Attempting direct IMAP connection to outlook.office365.com for: {email_address}")
    start_time = asyncio.get_event_loop().time()

    # Determine IMAP server host based on domain
    domain = email_address.split("@")[-1].lower() if "@" in email_address else ""
    if any(domain.endswith(d) for d in ["outlook.com", "hotmail.com", "live.com", "msn.com"]):
        imap_host = "outlook.office365.com"
    else:
        # Fallback host if custom domain
        imap_host = "outlook.office365.com"

    try:
        mail = imaplib.IMAP4_SSL(imap_host, 993)
        mail.login(email_address, password)
        logger.info("[IMAP-ENGINE] IMAP Authentication successful.")

        while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            mail.select("INBOX")
            
            # Search for unseen messages or all recent messages
            status, messages = mail.search(None, "UNSEEN")
            mail_ids = messages[0].split()
            
            if not mail_ids:
                # If no unseen messages, search all recent messages
                status, messages = mail.search(None, "ALL")
                mail_ids = messages[0].split()

            # Inspect the latest messages (reverse order)
            for msg_id in reversed(mail_ids[-5:]):
                status, msg_data = mail.fetch(msg_id, "(RFC822)")
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        
                        # Extract email body
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                content_disposition = str(part.get("Content-Disposition"))
                                if content_type in ["text/plain", "text/html"] and "attachment" not in content_disposition:
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        body += payload.decode(errors="ignore")
                        else:
                            payload = msg.get_payload(decode=True)
                            if payload:
                                body = payload.decode(errors="ignore")

                        # Parse 5-character alphanumeric verification code
                        match = re.search(r'\b[A-Z0-9]{5}\b', body)
                        if match:
                            code = match.group(0)
                            logger.info(f"[IMAP-ENGINE] Verification code successfully retrieved via IMAP: {code}")
                            mail.logout()
                            return code

            asyncio.run(asyncio.sleep(3))

        mail.logout()
        logger.warning("[IMAP-ENGINE] Polling timeout reached without finding verification code.")
        return None

    except Exception as err:
        logger.warning(f"[IMAP-ENGINE] Direct IMAP connection failed: {str(err)}. Will trigger browser fallback.")
        return None


# ============================================================================
# METHOD 2: Multi-Step Browser Extraction (Fallback)
# ============================================================================
async def fetch_code_via_browser_fallback(context: BrowserContext, email_address: str, password: str, timeout_seconds: int = 60) -> str:
    """
    Fallback browser automation for Microsoft login with explicit multi-step transition handling.
    """
    logger.info(f"[BROWSER-FALLBACK] Navigating to Microsoft Live login for: {email_address}")
    page = await context.new_page()

    try:
        await page.goto("https://login.live.com/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # Step 1: Input Email
        email_input = await page.wait_for_selector('input[type="email"], input[name="loginfmt"]', timeout=20000)
        await email_input.fill(email_address)

        # Click Next
        next_btn = await page.wait_for_selector('input[type="submit"], #idSIButton9', timeout=10000)
        await next_btn.click()
        logger.info("[BROWSER-FALLBACK] Submitted username. Waiting for password field to become visible...")

        # Step 2: Explicitly wait for Password Field to become visible (Multi-Step Transition)
        pass_input = await page.wait_for_selector(
            'input[type="password"]:visible, input[name="passwd"]:visible, #i0116:visible', 
            state="visible", 
            timeout=25000
        )
        await pass_input.fill(password)

        # Click Sign In
        signin_btn = await page.wait_for_selector('input[type="submit"], #idSIButton9', timeout=10000)
        await signin_btn.click()
        await page.wait_for_timeout(3000)

        # Handle "Stay Signed In?" Prompt if present
        stay_signed_btn = await page.query_selector('#idSIButton9, input[value="Yes"], #idBtn_Back')
        if stay_signed_btn:
            await stay_signed_btn.click()
            await page.wait_for_timeout(3000)

        # Navigate to Outlook Inbox
        await page.goto("https://outlook.live.com/mail/0/inbox", wait_until="domcontentloaded", timeout=30000)
        logger.info("[BROWSER-FALLBACK] Polling Outlook DOM for code...")

        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            page_text = await page.content()
            match = re.search(r'\b[A-Z0-9]{5}\b', page_text)
            if match:
                code = match.group(0)
                logger.info(f"[BROWSER-FALLBACK] Code retrieved from Outlook DOM: {code}")
                return code

            messages = await page.query_selector_all('div[role="option"], div[data-convid]')
            if messages:
                await messages[0].click()
                await page.wait_for_timeout(2000)

            await asyncio.sleep(4)

        raise TimeoutError("Browser fallback timed out before retrieving code.")

    finally:
        await page.close()


# ============================================================================
# SMART DISPATCHER
# ============================================================================
async def smart_get_verification_code(context: BrowserContext, email_address: str, password: str, timeout_seconds: int = 60) -> str:
    """
    Attempts direct IMAP retrieval first. If IMAP fails or is unavailable, 
    falls back to multi-step browser automation.
    """
    # 1. Primary Attempt: Direct IMAP
    loop = asyncio.get_running_loop()
    code = await loop.run_in_executor(None, fetch_code_via_imap, email_address, password, timeout_seconds)
    if code:
        return code

    # 2. Secondary Attempt: Browser Automation Fallback
    logger.info("[SMART-DISPATCHER] Direct IMAP failed or timed out. Engaging Browser Fallback Engine...")
    return await fetch_code_via_browser_fallback(context, email_address, password, timeout_seconds)


# ============================================================================
# AUTOMATION RUNNER CLASS
# ============================================================================
class AutomationRunner:
    def __init__(self, screenshot_dir: str = "./artifacts/screenshots"):
        self.screenshot_dir = screenshot_dir
        os.makedirs(self.screenshot_dir, exist_ok=True)
        self.browser = None
        self.playwright = None

    async def initialize(self):
        logger.info("[AUTOMATION] Warm browser runner initialized successfully.")
        return True

    async def cleanup(self):
        logger.info("[AUTOMATION] Cleaning up browser runner resources.")
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def execute_task(self, *args, **kwargs) -> dict:
        task_data = {}
        extra_target = None

        if args:
            for arg in args:
                if isinstance(arg, dict):
                    task_data = arg
                elif isinstance(arg, str):
                    extra_target = arg

        if kwargs:
            if "task_data" in kwargs and isinstance(kwargs["task_data"], dict):
                task_data = kwargs["task_data"]
            else:
                task_data.update(kwargs)

        steam_user = task_data.get("steam_username", "")
        steam_pass = task_data.get("steam_password", "")
        orig_email = task_data.get("original_email", "")
        email_pass = task_data.get("email_password", "")
        new_email = task_data.get("target_email") or task_data.get("target_contact") or extra_target or ""

        logger.info(f"[STEALTH-RUNNER] Executing workflow for user: {steam_user} (Mail: {orig_email})")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=STEALTH_ARGS)
            context = await browser.new_context(
                viewport={"width": 1366, "height": 768},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="Europe/Stockholm",
            )

            page = await context.new_page()
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            try:
                # 1. Login to Steam
                logger.info("[STEP 1] Navigating to Steam login...")
                await page.goto("https://store.steampowered.com/login/", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)

                user_input = await page.wait_for_selector('input[type="text"]:visible, input#input_username', timeout=25000)
                await user_input.fill(steam_user)

                pass_input = await page.wait_for_selector('input[type="password"]:visible, input#input_password', timeout=10000)
                await pass_input.fill(steam_pass)

                submit_btn = await page.query_selector('button[type="submit"]:visible, button:has-text("Sign in")')
                if submit_btn:
                    await submit_btn.click()
                    logger.info("[STEP 2] Login submitted. Navigating to account settings...")
                    await page.wait_for_timeout(4000)

                # 2. Access Account Settings
                await page.goto("https://store.steampowered.com/account/", wait_until="domcontentloaded", timeout=30000)
                
                change_email_btn = await page.query_selector('a[href*="changeemail"], button:has-text("Change my email address")')
                if change_email_btn:
                    await change_email_btn.click()
                    await page.wait_for_timeout(2000)

                # 3. Trigger Verification Code Dispatch
                send_code_btn = await page.query_selector('button[type="submit"], .btn_blue_steamui')
                if send_code_btn:
                    await send_code_btn.click()
                    logger.info("[STEP 3] Triggered verification code email from Steam.")
                    await page.wait_for_timeout(3000)

                # 4. Fetch Code (IMAP First, Browser Fallback Second)
                logger.info("[STEP 4] Fetching verification code via IMAP / Smart Dispatcher...")
                verification_code = await smart_get_verification_code(
                    context=context,
                    email_address=orig_email,
                    password=email_pass,
                    timeout_seconds=60
                )

                if not verification_code:
                    raise RuntimeError("Failed to retrieve verification code via both IMAP and Browser Fallback.")

                # 5. Input Code and Update Email
                logger.info(f"[STEP 5] Submitting code '{verification_code}' to Steam...")
                code_input = await page.wait_for_selector("input[type='text'], input[name='code'], input#email_authcode", timeout=15000)
                await code_input.fill(verification_code)

                confirm_code_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui")
                if confirm_code_btn:
                    await confirm_code_btn.click()
                    await page.wait_for_timeout(4000)

                logger.info(f"[STEP 6] Entering target email address: {new_email}")
                new_email_input = await page.wait_for_selector("input#email, input[type='email'], input[name='new_email']", timeout=15000)
                await new_email_input.fill(new_email)

                final_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui")
                if final_btn:
                    await final_btn.click()
                    await page.wait_for_timeout(4000)

                logger.info("[SUCCESS] Account email update completed successfully!")
                return {"status": "success", "message": "Email updated successfully", "code": verification_code}

            except Exception as e:
                screenshot_path = os.path.join(self.screenshot_dir, f"error_{steam_user}.png")
                await page.screenshot(path=screenshot_path)
                logger.error(f"[ERROR] Task failed: {str(e)}. Error screenshot saved to {screenshot_path}")
                raise e

            finally:
                await context.close()
                await browser.close()
