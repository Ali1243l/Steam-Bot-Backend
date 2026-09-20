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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()

        steam_user = task_payload.get("account_identifier")
        steam_pass = task_payload.get("account_secret")
        orig_email = task_payload.get("original_email")
        email_pass = task_payload.get("email_password")
        new_email = task_payload.get("target_contact")

        try:
            logger.info(f"Logging into Steam for user: {steam_user}")
            await page.goto("https://store.steampowered.com/login/", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3000)

            # 1. إدخال اسم المستخدم
            user_selector = "input#input_username, input[type='text']:visible, input[name='username']"
            await page.wait_for_selector(user_selector, timeout=30000)
            user_el = await page.query_selector(user_selector)
            if user_el:
                await user_el.click(force=True)
                await user_el.fill(steam_user)

            # 2. إدخال كلمة المرور والضغط على Enter
            pwd_selector = "input#input_password, input[type='password']:visible, input[name='password']"
            await page.wait_for_selector(pwd_selector, timeout=15000)
            pwd_el = await page.query_selector(pwd_selector)
            if pwd_el:
                await pwd_el.click(force=True)
                await pwd_el.fill(steam_pass)
                await page.keyboard.press("Enter")
            else:
                submit_btn = await page.query_selector("button[type='submit']")
                if submit_btn:
                    await submit_btn.click(force=True)

            await page.wait_for_timeout(8000)

            # 3. التوجه المباشر لرابط تغيير الإيميل
            logger.info("Navigating to Steam Change Email wizard...")
            await page.goto("https://help.steampowered.com/en/wizard/HelpChangeEmail/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)

            # 4. الضغط على خيار إرسال الكود
            send_code_btn = await page.query_selector("button:has-text('Email'), .btn_blue_steamui, #email_verification_dialog button, a:has-text('Email')")
            if send_code_btn:
                await send_code_btn.click(force=True)
                logger.info("Clicked request verification code on Steam.")

            await page.wait_for_timeout(5000)

            # 5. جلب كود التحقق من بريد xomail
            logger.info(f"Fetching code from xomail for: {orig_email}")
            verification_code = await fetch_code_from_xomail(
                context=context,
                email=orig_email,
                password=email_pass,
                timeout_seconds=60
            )
            logger.info(f"Extracted Verification Code: {verification_code}")

            # 6. كتابة كود التحقق وتأكيده
            code_selector = "input[name='code'], input[type='text']:visible"
            code_input = await page.wait_for_selector(code_selector, timeout=20000)
            if code_input:
                await code_input.click(force=True)
                await code_input.fill(verification_code)

            submit_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui, input[type='submit']")
            if submit_btn:
                await submit_btn.click(force=True)
            
            # ننتظر 6 ثواني حتى يحمل ستيم الفورم الخاص بالإيميل الجديد
            await page.wait_for_timeout(6000)

            # 7. إدخال الإيميل الجديد (دعم كل محددات ستيم المحتملة)
            logger.info(f"Entering new target email: {new_email}")
            new_email_selector = "input#email_input, input#email, input[name='new_email'], input[type='email'], input[type='text']:visible"
            new_email_input = await page.wait_for_selector(new_email_selector, timeout=25000)
            if new_email_input:
                await new_email_input.click(force=True)
                await new_email_input.fill(new_email)

            confirm_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui, input[type='submit'], button:has-text('Change Email')")
            if confirm_btn:
                await confirm_btn.click(force=True)
            
            await page.wait_for_timeout(5000)

            logger.info("Email change process completed successfully! Verification link/code dispatched to target.")
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
