"""
browser_engine.py - Anti-Bot Stealth Engine for AWS / Cloud Instances
"""

import re
import os
import asyncio
import logging
from typing import Dict, Any, Optional
from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("browser_engine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# خيارات متصفح متقدمة لتجاوز كشف AWS EC2 Data Center IPs
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


async def fetch_code_from_xomail(context: BrowserContext, email: str, password: str, timeout_seconds: int = 60) -> str:
    logger.info(f"[WEBMAIL] Opening secondary tab for: {email}")
    webmail_page = await context.new_page()

    try:
        await webmail_page.goto("http://xomail.club/", wait_until="domcontentloaded", timeout=30000)

        await webmail_page.fill("#rcmloginuser", email)
        await webmail_page.fill("#rcmloginpwd", password)
        await webmail_page.click("#rcmloginsubmit")
        await webmail_page.wait_for_load_state("domcontentloaded")

        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            messages = await webmail_page.query_selector_all("table#messagelist tr.message")
            if messages:
                logger.info("[WEBMAIL] Found email message in inbox...")
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

                match = re.search(r'\b[A-Z0-9]{5}\b', body_text)
                if match:
                    code = match.group(0)
                    logger.info(f"[WEBMAIL] Code extracted: {code}")
                    return code

            refresh_btn = await webmail_page.query_selector("a.button.toolbar-button.refresh, #rcmbtn100")
            if refresh_btn:
                await refresh_btn.click()

            await asyncio.sleep(3)

        raise TimeoutError(f"Verification email timeout after {timeout_seconds}s")

    finally:
        await webmail_page.close()


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
        """
        تستقبل البيانات بدون أي خطأ في عدد المتغيرات الممررة من main.py
        """
        task_data = {}
        extra_target = None

        # التعامل مع أية طريقة استدعاء ممررة من main.py
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

        logger.info(f"[STEALTH-RUNNER] Starting Steam automation for user: {steam_user}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=STEALTH_ARGS)
            context = await browser.new_context(
                viewport={"width": 1366, "height": 768},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="Europe/Stockholm",
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                }
            )

            page = await context.new_page()
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            try:
                logger.info("[STEP 1] Opening Steam login page with Anti-Detect headers...")
                await page.goto("https://store.steampowered.com/login/", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)

                page_title = await page.title()
                logger.info(f"[PAGE TITLE]: {page_title}")

                user_input = await page.wait_for_selector('input[type="text"]:visible, input#input_username, input[name="username"]', timeout=25000)
                await user_input.fill(steam_user)

                pass_input = await page.wait_for_selector('input[type="password"]:visible, input#input_password', timeout=10000)
                await pass_input.fill(steam_pass)

                submit_btn = await page.query_selector('button[type="submit"]:visible, button:has-text("Sign in")')
                if submit_btn:
                    await submit_btn.click()
                    logger.info("[STEP 2] Submitted credentials. Waiting for authentication...")
                    await page.wait_for_timeout(5000)

                logger.info("[STEP 3] Opening Account Settings...")
                await page.goto("https://store.steampowered.com/account/", wait_until="domcontentloaded", timeout=30000)

                change_email_btn = await page.query_selector('a[href*="changeemail"], button:has-text("Change my email address")')
                if change_email_btn:
                    await change_email_btn.click()
                    await page.wait_for_timeout(2000)

                send_code_btn = await page.query_selector('button[type="submit"], .btn_blue_steamui')
                if send_code_btn:
                    await send_code_btn.click()
                    logger.info("[STEP 4] Requested verification code dispatch.")
                    await page.wait_for_timeout(3000)

                logger.info("[STEP 5] Fetching code from xomail...")
                verification_code = await fetch_code_from_xomail(
                    context=context,
                    email=orig_email,
                    password=email_pass,
                    timeout_seconds=60
                )

                logger.info(f"[STEP 6] Submitting extracted code: {verification_code}")
                code_input = await page.wait_for_selector("input[type='text'], input[name='code'], input#email_authcode", timeout=15000)
                await code_input.fill(verification_code)

                confirm_code_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui")
                if confirm_code_btn:
                    await confirm_code_btn.click()
                    await page.wait_for_timeout(4000)

                new_email_input = await page.wait_for_selector("input#email, input[type='email'], input[name='new_email']", timeout=15000)
                await new_email_input.fill(new_email)

                final_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui")
                if final_btn:
                    await final_btn.click()
                    await page.wait_for_timeout(4000)

                logger.info("[SUCCESS] Account automation finished successfully!")
                return {"status": "success", "message": "Email updated successfully", "code": verification_code}

            except Exception as e:
                screenshot_path = os.path.join(self.screenshot_dir, f"error_{steam_user}.png")
                await page.screenshot(path=screenshot_path)
                logger.error(f"[ERROR] Task failed: {str(e)}. Saved error screenshot to {screenshot_path}")
                raise e

            finally:
                await context.close()
                await browser.close()
