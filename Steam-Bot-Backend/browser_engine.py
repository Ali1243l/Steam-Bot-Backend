import asyncio
import logging
import os
from playwright.async_api import async_playwright
from mail_extractor import fetch_code_from_xomail
from supabase import create_client

logger = logging.getLogger("orchestrator.browser")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()

class AutomationRunner:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

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

        account_id = task_payload.get("account_id")
        steam_user = task_payload.get("account_identifier")
        steam_pass = task_payload.get("account_secret")
        orig_email = task_payload.get("original_email")
        email_pass = task_payload.get("email_password")
        new_email = task_payload.get("target_contact")

        try:
            # 1. التوجه مباشرة لصفحة المساعدة
            logger.info("Opening Steam Help Change Email page directly...")
            await page.goto("https://help.steampowered.com/en/wizard/HelpChangeEmail/", wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(3000)

            # تسجيل الدخول إن طُلب
            if "login" in page.url.lower():
                logger.info(f"Steam Help requested login. Entering credentials for user: {steam_user}")
                user_selector = "input[type='text']:visible, input#input_username, input[name='username']"
                await page.wait_for_selector(user_selector, timeout=25000)
                user_el = await page.query_selector(user_selector)
                if user_el:
                    await user_el.click(force=True)
                    await user_el.fill("")
                    await page.keyboard.type(steam_user, delay=40)

                pwd_selector = "input[type='password']:visible, input#input_password, input[name='password']"
                await page.wait_for_selector(pwd_selector, timeout=15000)
                pwd_el = await page.query_selector(pwd_selector)
                if pwd_el:
                    await pwd_el.click(force=True)
                    await pwd_el.fill("")
                    await page.keyboard.type(steam_pass, delay=40)

                submit_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui, input[type='submit']")
                if submit_btn:
                    await submit_btn.click(force=True)
                else:
                    await page.keyboard.press("Enter")

                await page.wait_for_timeout(7000)

            logger.info(f"Current Help Wizard URL: {page.url}")
            await page.wait_for_timeout(2000)

            # 2. الضغط الحصري على خيار إرسال الكود داخل جسم الصفحة (تجنب قوائم اللغات)
            # المحدد يستهدف النص الظاهر بالصفحة حصراً
            target_button = await page.wait_for_selector(
                "xpath=//a[contains(., 'Email an account verification code')] | //button[contains(., 'Email an account verification code')]",
                timeout=20000
            )
            if target_button:
                await target_button.click(force=True)
                logger.info("[STEAM:SUCCESS] Clicked 'Email an account verification code' successfully!")
            
            # مهلة 12 ثانية لوصول الرسالة من ستيم إلى سيرفر xomail
            logger.info("Waiting 12 seconds for Steam email dispatch...")
            await page.wait_for_timeout(12000)

            # 3. جلب كود التحقق الفعلي من بريد xomail
            logger.info(f"Fetching Change-Email verification code from xomail for: {orig_email}")
            change_email_code = await fetch_code_from_xomail(
                context=context,
                email=orig_email,
                password=email_pass,
                timeout_seconds=60
            )
            logger.info(f"[STEAM_VERIFICATION_CODE]: {change_email_code}")

            # 4. إدخال الكود المستخرج وتأكيده
            code_input = await page.wait_for_selector("input[name='code'], input[type='text']:visible", timeout=20000)
            if code_input:
                await code_input.click(force=True)
                await code_input.fill(change_email_code)
                await page.keyboard.press("Enter")

            submit_wizard_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui, input[type='submit']")
            if submit_wizard_btn:
                await submit_wizard_btn.click(force=True)

            await page.wait_for_timeout(6000)

            # 5. كتابة الإيميل الجديد
            logger.info(f"Entering target new email: {new_email}")
            new_email_selector = "input#email_input, input#email, input[name='new_email'], input[type='text']:visible"
            new_email_input = await page.wait_for_selector(new_email_selector, timeout=25000)
            if new_email_input:
                await new_email_input.click(force=True)
                await new_email_input.fill("")
                await page.keyboard.type(new_email, delay=40)
                await page.keyboard.press("Enter")

            confirm_change_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui, button:has-text('Change Email')")
            if confirm_change_btn:
                await confirm_change_btn.click(force=True)

            await page.wait_for_timeout(6000)

            # 6. مرحلة انتظار الكود من الواجهة (المستلم على إيميلك الشخصي)
            if self.supabase and account_id:
                logger.info(f"[WAITING] Setting status to 'waiting_code' for account {account_id}...")
                self.supabase.table("stock_accounts").update({
                    "status": "waiting_code",
                    "target_verification_code": None
                }).eq("id", account_id).execute()

                user_code = None
                for _ in range(60):
                    await asyncio.sleep(2)
                    res = self.supabase.table("stock_accounts").select("target_verification_code").eq("id", account_id).execute()
                    if res.data and res.data[0].get("target_verification_code"):
                        user_code = str(res.data[0]["target_verification_code"]).strip()
                        break

                if not user_code:
                    raise TimeoutError("User did not submit target verification code in time.")

                logger.info(f"[RECEIVED] Submitting user target code: {user_code}")
                final_input = await page.wait_for_selector("input[name='code'], input[type='text']:visible", timeout=15000)
                if final_input:
                    await final_input.click(force=True)
                    await final_input.fill(user_code)
                    await page.keyboard.press("Enter")

                await page.wait_for_timeout(5000)

            logger.info("Process finished successfully! Steam email updated.")
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
