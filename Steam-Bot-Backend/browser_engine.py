"""
browser_engine.py - Smart Multi-Provider Anti-Bot Engine for AWS
Dynamically routes verification requests based on Email Domain (@outlook.com, @hotmail.com, @fjqtabk.icu, etc.)
"""

import re
import os
import asyncio
import logging
from typing import Dict, Any, Optional
from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

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


def detect_email_provider(email: str) -> str:
    """الخوارزمية الذكية: فحص دومين الإيميل وتحديد المزود تلقائياً"""
    if not email or "@" not in email:
        return "xomail"
    domain = email.split("@")[-1].lower().strip()
    microsoft_domains = ["outlook.com", "hotmail.com", "live.com", "msn.com", "passport.com"]
    if any(domain.endswith(d) for d in microsoft_domains):
        return "outlook"
    return "xomail"


async def fetch_code_from_outlook(context: BrowserContext, email: str, password: str, timeout_seconds: int = 60) -> str:
    """محرك مخصص لتسجيل الدخول إلى Outlook و Hotmail واستخراج الرمز"""
    logger.info(f"[OUTLOOK-ENGINE] Opening tab for Microsoft Outlook login: {email}")
    page = await context.new_page()

    try:
        # 1. فتح صفحة تسجيل الدخول لـ Microsoft Outlook
        await page.goto("https://login.live.com/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # كتابة ايميل Outlook
        email_input = await page.wait_for_selector('input[type="email"], input[name="loginfmt"]', timeout=20000)
        await email_input.fill(email)
        
        next_btn = await page.query_selector('input[type="submit"], #idSIButton9')
        if next_btn:
            await next_btn.click()
            await page.wait_for_timeout(2500)

        # كتابة الباسورد
        pass_input = await page.wait_for_selector('input[type="password"], input[name="passwd"]', timeout=20000)
        await pass_input.fill(password)

        signin_btn = await page.query_selector('input[type="submit"], #idSIButton9, button[type="submit"]')
        if signin_btn:
            await signin_btn.click()
            await page.wait_for_timeout(3000)

        # تخطي سؤال الإبقاء على تسجيل الدخول Stay signed in
        stay_signed_btn = await page.query_selector('#idSIButton9, input[value="Yes"], button:has-text("Yes"), #idBtn_Back')
        if stay_signed_btn:
            await stay_signed_btn.click()
            await page.wait_for_timeout(3000)

        # 2. الانتقال لصندوق الوارد لـ Outlook
        await page.goto("https://outlook.live.com/mail/0/inbox", wait_until="domcontentloaded", timeout=30000)
        logger.info("[OUTLOOK-ENGINE] Polling Outlook inbox for verification code...")

        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            page_text = await page.content()
            
            # البحث عن رمز مكون من 5 خانات
            match = re.search(r'\b[A-Z0-9]{5}\b', page_text)
            if match:
                code = match.group(0)
                logger.info(f"[OUTLOOK-ENGINE] Code successfully extracted: {code}")
                return code

            # فتح أول رسالة إيميل في القائمة
            messages = await page.query_selector_all('div[role="option"], div[data-convid], div.customGroupHeader')
            if messages:
                await messages[0].click()
                await page.wait_for_timeout(2000)

            await asyncio.sleep(4)

        raise TimeoutError(f"Outlook verification email timeout after {timeout_seconds}s")

    finally:
        await page.close()


async def fetch_code_from_xomail(context: BrowserContext, email: str, password: str, timeout_seconds: int = 60) -> str:
    """محرك مخصص لتسجيل الدخول إلى Roundcube Webmail (xomail.club)"""
    logger.info(f"[XOMAIL-ENGINE] Opening secondary tab for Roundcube: {email}")
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
                logger.info("[XOMAIL-ENGINE] Found email message in inbox...")
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
                    logger.info(f"[XOMAIL-ENGINE] Code extracted: {code}")
                    return code

            refresh_btn = await webmail_page.query_selector("a.button.toolbar-button.refresh, #rcmbtn100")
            if refresh_btn:
                await refresh_btn.click()

            await asyncio.sleep(3)

        raise TimeoutError(f"xomail verification email timeout after {timeout_seconds}s")

    finally:
        await webmail_page.close()


async def smart_fetch_verification_code(context: BrowserContext, email: str, password: str, timeout_seconds: int = 60) -> str:
    """الموزع الذكي: يوجه الطلب تلقائياً بناءً على نوع دومين الإيميل"""
    provider = detect_email_provider(email)
    logger.info(f"[SMART-ROUTER] Detected email provider '{provider}' for account: {email}")

    if provider == "outlook":
        return await fetch_code_from_outlook(context, email, password, timeout_seconds)
    else:
        return await fetch_code_from_xomail(context, email, password, timeout_seconds)


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

        logger.info(f"[STEALTH-RUNNER] Starting Steam automation for user: {steam_user} (Email: {orig_email})")

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

                logger.info("[STEP 5] Smart Routing: Fetching code based on Email Provider...")
                verification_code = await smart_fetch_verification_code(
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
