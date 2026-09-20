"""
browser_engine.py - Robust Playwright Automation Engine for Account Provisioning
"""

import re
import asyncio
import logging
from typing import Dict, Any, Optional
from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("browser_engine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Chromium flags optimized for memory-constrained container environments (e.g., Render 512MB RAM)
RAM_OPTIMIZED_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-accelerated-2d-canvas",
    "--no-first-run",
    "--no-zygote",
    "--single-process",
    "--disable-gpu",
    "--disable-extensions",
]

# Combined fallback locators for Steam username & password fields across legacy and modern UI variations
USERNAME_SELECTORS = [
    "input[type='text']:visible",
    "input.newlog_input_22p4A",
    "#responsive_login_login_wrapper input[type='text']",
    "input#input_username",
    "input[name='username']",
]

PASSWORD_SELECTORS = [
    "input[type='password']:visible",
    "input#input_password",
    "input[name='password']",
]

SUBMIT_LOGIN_SELECTORS = [
    "button[type='submit']:visible",
    "button:has-text('Sign in')",
    "button:has-text('تسجيل الدخول')",
    "#responsive_login_login_button button",
]


async def fetch_code_from_xomail(context: BrowserContext, email: str, password: str, timeout_seconds: int = 60) -> str:
    """
    Logs into xomail.club in a secondary tab, polls the inbox, extracts 
    the 5-character verification code, and closes the tab.
    """
    logger.info(f"[WEBMAIL] Opening secondary tab to fetch verification code for: {email}")
    webmail_page = await context.new_page()

    try:
        await webmail_page.goto("http://xomail.club/", wait_until="domcontentloaded", timeout=30000)

        # Authenticate with Roundcube webmail
        await webmail_page.fill("#rcmloginuser", email)
        await webmail_page.fill("#rcmloginpwd", password)
        await webmail_page.click("#rcmloginsubmit")
        await webmail_page.wait_for_load_state("domcontentloaded")

        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            messages = await webmail_page.query_selector_all("table#messagelist tr.message")
            if messages:
                logger.info("[WEBMAIL] Message detected in inbox. Opening email...")
                await messages[0].click()
                await webmail_page.wait_for_timeout(2000)

                body_text = ""
                frame_element = await webmail_page.query_selector("iframe#messagecontframe")
                if frame_element:
                    frame = await frame_element.content_frame()
                    if frame:
                        await frame.wait_for_load_state("domcontentloaded")
                        body_text = await frame.content()
                else:
                    content_elem = await webmail_page.query_selector("div.message-part")
                    if content_elem:
                        body_text = await content_elem.inner_text()

                # Extract 5-character alphanumeric verification code
                match = re.search(r'\b[A-Z0-9]{5}\b', body_text)
                if match:
                    code = match.group(0)
                    logger.info(f"[WEBMAIL] Successfully extracted verification code: {code}")
                    return code

            refresh_btn = await webmail_page.query_selector("a.button.toolbar-button.refresh, #rcmbtn100")
            if refresh_btn:
                await refresh_btn.click()

            await asyncio.sleep(3)

        raise TimeoutError(f"Verification email did not arrive within {timeout_seconds} seconds.")

    finally:
        await webmail_page.close()


class AutomationRunner:
    """
    Manages browser lifecycle and executes end-to-end account orchestration.
    """
    def __init__(self, screenshot_dir: str = "./artifacts/screenshots"):
        self.screenshot_dir = screenshot_dir

    async def _find_and_fill(self, page: Page, selectors: list[str], value: str, timeout: int = 15000) -> bool:
        """
        Attempts to locate and fill an input using a prioritized list of CSS selectors.
        """
        combined_selector = ", ".join(selectors)
        try:
            element = await page.wait_for_selector(combined_selector, timeout=timeout, state="visible")
            if element:
                await element.fill(value)
                return True
        except PlaywrightTimeoutError:
            logger.warning(f"[AUTOMATION] Selector group timed out: {selectors}")
        return False

    async def execute_task(self, task_data: dict) -> dict:
        steam_user = task_data.get("steam_username", "")
        steam_pass = task_data.get("steam_password", "")
        orig_email = task_data.get("original_email", "")
        email_pass = task_data.get("email_password", "")
        new_email = task_data.get("target_email") or task_data.get("target_contact", "")

        logger.info(f"[AUTOMATION:START] Executing task for account: {steam_user}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=RAM_OPTIMIZED_ARGS)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

            try:
                page = await context.new_page()

                # Step 1: Navigate to Steam Login / Account Page
                logger.info("[STEP 1] Navigating to target portal...")
                await page.goto("https://store.steampowered.com/login/", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)

                # Step 2: Session Check — Skip login if already authenticated or on verification screen
                current_url = page.url
                is_already_authenticated = "/account" in current_url or await page.query_selector("input#email_authcode, input[name='code']") is not None

                if is_already_authenticated:
                    logger.info("[STEP 2] Active session detected or already on verification prompt. Skipping login step.")
                else:
                    logger.info("[STEP 2] Session not authenticated. Filling login credentials...")
                    
                    # Fill Username with multi-selector fallback
                    username_filled = await self._find_and_fill(page, USERNAME_SELECTORS, steam_user, timeout=20000)
                    if not username_filled:
                        raise RuntimeError("Failed to locate Steam username input field using all fallback locators.")

                    # Fill Password
                    password_filled = await self._find_and_fill(page, PASSWORD_SELECTORS, steam_pass, timeout=10000)
                    if not password_filled:
                        raise RuntimeError("Failed to locate Steam password input field using all fallback locators.")

                    # Submit Login
                    combined_submit = ", ".join(SUBMIT_LOGIN_SELECTORS)
                    submit_btn = await page.query_selector(combined_submit)
                    if submit_btn:
                        await submit_btn.click()
                        logger.info("[STEP 2] Clicked login submit button. Awaiting navigation...")
                        await page.wait_for_timeout(5000)

                # Step 3: Navigate to Email Change Settings
                logger.info("[STEP 3] Accessing account settings page...")
                await page.goto("https://store.steampowered.com/account/", wait_until="domcontentloaded", timeout=30000)

                change_email_btn = await page.query_selector('a[href*="changeemail"], button:has-text("Change my email address")')
                if change_email_btn:
                    await change_email_btn.click()
                    await page.wait_for_timeout(2000)

                # Step 4: Dispatch Verification Code Request
                send_code_btn = await page.query_selector('button[type="submit"], .btn_blue_steamui, button:has-text("Send")')
                if send_code_btn:
                    await send_code_btn.click()
                    logger.info("[STEP 4] Requested verification code dispatch to original email.")
                    await page.wait_for_timeout(3000)

                # Step 5: Fetch Code from Webmail
                logger.info("[STEP 5] Initiating webmail extraction via Tab 2...")
                verification_code = await fetch_code_from_xomail(
                    context=context,
                    email=orig_email,
                    password=email_pass,
                    timeout_seconds=60
                )
                logger.info(f"[STEP 5] Code retrieved: {verification_code}")

                # Step 6: Submit Code & Finalize Target Email Update
                logger.info("[STEP 6] Submitting verification code on target portal...")
                code_input = await page.wait_for_selector("input[type='text'], input[name='code'], input#email_authcode", timeout=15000)
                await code_input.fill(verification_code)

                submit_code_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui")
                if submit_code_btn:
                    await submit_code_btn.click()
                    await page.wait_for_timeout(4000)

                # Enter New Target Email
                logger.info(f"[STEP 6] Entering target email: {new_email}")
                new_email_input = await page.wait_for_selector("input#email, input[type='email'], input[name='new_email']", timeout=15000)
                await new_email_input.fill(new_email)

                confirm_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui")
                if confirm_btn:
                    await confirm_btn.click()
                    await page.wait_for_timeout(4000)

                logger.info("[AUTOMATION:SUCCESS] Account email updated successfully!")
                return {"status": "success", "message": "Email updated successfully", "code": verification_code}

            except Exception as e:
                logger.error(f"[AUTOMATION:ERROR] Execution failed: {str(e)}")
                raise e

            finally:
                await context.close()
                await browser.close()
                logger.info("[AUTOMATION:CLEANUP] Browser instance and context destroyed.")
