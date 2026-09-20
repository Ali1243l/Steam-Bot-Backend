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

            # 1. إدخال بيانات ستيم بالمحددات الدقيقة
            logger.info(f"Logging into Steam for user: {steam_user}")
            await page.goto("https://store.steampowered.com/login/", wait_until="domcontentloaded", timeout=45000)
            
            # انتظار ظهور أي حقل نصي لتسجيل الدخول
            username_selector = "input#input_username, input[type='text']:visible, input[name='username']"
            await page.wait_for_selector(username_selector, timeout=30000)
            
            # تعبئة اسم المستخدم
            user_input = await page.query_selector(username_selector)
            if user_input:
                await user_input.click()
                await user_input.fill("")
                await page.keyboard.type(steam_user, delay=50)

            # تعبئة كلمة المرور
            password_selector = "input#input_password, input[type='password']:visible, input[name='password']"
            await page.wait_for_selector(password_selector, timeout=15000)
            pwd_input = await page.query_selector(password_selector)
            if pwd_input:
                await pwd_input.click()
                await pwd_input.fill("")
                await page.keyboard.type(steam_pass, delay=50)

            # الضغط على زر تسجيل الدخول
            submit_btn = await page.wait_for_selector("button[type='submit'], .btn_blue_steamui, button:has-text('Sign In'), button:has-text('Log in')", timeout=15000)
            if submit_btn:
                await submit_btn.click()

            # مهلة للتأكد من نجاح جلسة تسجيل الدخول
            await page.wait_for_timeout(8000)
            # 2. التوجه لرابط تغيير الإيميل
            logger.info("Navigating to Steam Change Email wizard...")
            await page.goto("https://help.steampowered.com/en/wizard/HelpChangeEmail/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)

            # 3. طلب كود التحقق
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
            await page.goto("https://store.steampowered.com/login/", wait_until="domcontentloaded", timeout=45000)

            # 1. إدخال بيانات ستيم
            username_selector = "input#input_username, input[type='text']:visible, input[name='username']"
            await page.wait_for_selector(username_selector, timeout=30000)
            user_input = await page.query_selector(username_selector)
            if user_input:
                await user_input.click()
                await user_input.fill("")
                await page.keyboard.type(steam_user, delay=50)

            password_selector = "input#input_password, input[type='password']:visible, input[name='password']"
            await page.wait_for_selector(password_selector, timeout=15000)
            pwd_input = await page.query_selector(password_selector)
            if pwd_input:
                await pwd_input.click()
                await pwd_input.fill("")
                await page.keyboard.type(steam_pass, delay=50)
                # استخدام زر Enter لتجاوز اعتراض المنيو العلوي
                await page.keyboard.press("Enter")
            else:
                submit_btn = await page.query_selector("button[type='submit']")
                if submit_btn:
                    await submit_btn.click(force=True)

            # انتظار اكتمال الدخول وتحميل الجلسة
            await page.wait_for_timeout(8000)

            # 2. التوجه المباشر لصفحة تغيير الإيميل
            logger.info("Navigating to Steam Change Email wizard...")
            await page.goto("https://help.steampowered.com/en/wizard/HelpChangeEmail/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)

            # 3. الضغط على خيار إرسال الكود للإيميل القديم
            send_code_btn = await page.query_selector("button:has-text('Email'), .btn_blue_steamui, #email_verification_dialog button")
            if send_code_btn:
                await send_code_btn.click(force=True)
                logger.info("Clicked request verification code on Steam.")

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

            # 5. كتابة كود التحقق وتأكيده
            code_input = await page.wait_for_selector("input[type='text'], input[name='code']", timeout=15000)
            await code_input.fill(verification_code)

            submit_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui")
            if submit_btn:
                await submit_btn.click(force=True)
            await page.wait_for_timeout(4000)

            # 6. إدخال الإيميل الجديد وتأكيده
            logger.info(f"Entering new target email: {new_email}")
            new_email_input = await page.wait_for_selector("input#email, input[type='email'], input[name='new_email']", timeout=15000)
            await new_email_input.fill(new_email)

            confirm_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui")
            if confirm_btn:
                await confirm_btn.click(force=True)
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

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
