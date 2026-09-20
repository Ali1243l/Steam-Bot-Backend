import asyncio
import logging
from playwright.async_api import async_playwright
from mail_extractor import fetch_code_from_xomail

logger = logging.getLogger("orchestrator.browser")

class AutomationRunner:
    def __init__(self):
        self.playwright = None
        self.browser = None

    async def initialize(self):
        if not self.playwright:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu"
                ]
            )

    async def execute_task(self, target_dashboard_url: str, task_payload: dict) -> dict:
        await self.initialize()
        context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        steam_user = task_payload.get("account_identifier")
        steam_pass = task_payload.get("account_secret")
        orig_email = task_payload.get("original_email")
        email_pass = task_payload.get("email_password")
        new_email = task_payload.get("target_contact")

        try:
            logger.info(f"Logging into Steam for user: {steam_user}")
            await page.goto("https://store.steampowered.com/login/", wait_until="networkidle", timeout=30000)

            # 1. إدخال بيانات ستيم
            inputs = await page.query_selector_all("input[type='text']")
            if inputs:
                await inputs[0].fill(steam_user)
            await page.fill("input[type='password']", steam_pass)
            await page.click("button[type='submit']")

            # انتظار تسجيل الدخول
            await page.wait_for_timeout(7000)

            # 2. التوجه مباشرة لرابط تغيير الإيميل
            logger.info("Navigating to Steam Change Email wizard...")
            await page.goto("https://help.steampowered.com/en/wizard/HelpChangeEmail/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)

            # 3. الضغط على زر إرسال الكود للإيميل القديم
            send_code_btn = await page.query_selector("button:has-text('Email'), .btn_blue_steamui")
            if send_code_btn:
                await send_code_btn.click()
                logger.info("Clicked request verification code on Steam.")
            else:
                logger.info("Proceeding to code verification stage...")

            await page.wait_for_timeout(5000)

            # 4. جلب الكود من صندوق xomail
            logger.info(f"Fetching code from xomail for: {orig_email}")
            verification_code = await fetch_code_from_xomail(
                context=context,
                email=orig_email,
                password=email_pass,
                timeout_seconds=60
            )
            logger.info(f"Extracted Verification Code: {verification_code}")

            # 5. إدخال الكود المستلم في صفحة ستيم
            code_input = await page.wait_for_selector("input[type='text'], input[name='code']", timeout=15000)
            await code_input.fill(verification_code)
            
            submit_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui")
            if submit_btn:
                await submit_btn.click()
            await page.wait_for_timeout(4000)

            # 6. كتابة الإيميل الجديد وحفظه
            logger.info(f"Entering new target email: {new_email}")
            new_email_input = await page.wait_for_selector("input#email, input[type='email'], input[name='new_email']", timeout=15000)
            await new_email_input.fill(new_email)

            confirm_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui")
            if confirm_btn:
                await confirm_btn.click()
            await page.wait_for_timeout(5000)

            logger.info("Email change process completed successfully!")
            return {"status": "success", "message": "Email updated successfully"}

        except Exception as e:
            logger.error(f"Error during browser automation: {str(e)}")
            raise e
        finally:
            await context.close()

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
