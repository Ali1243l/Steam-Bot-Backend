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
            logger.info(f"Logging into Steam for user: {steam_user}")
            await page.goto("https://store.steampowered.com/login/", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3000)

            # 1. تسجيل الدخول
            user_selector = "input#input_username, input[type='text']:visible, input[name='username']"
            await page.wait_for_selector(user_selector, timeout=30000)
            user_el = await page.query_selector(user_selector)
            if user_el:
                await user_el.click(force=True)
                await user_el.fill(steam_user)

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

            # 2. التوجه المباشر لرابط تغيير الإيميل
            logger.info("Navigating to Steam Change Email wizard...")
            await page.goto("https://help.steampowered.com/en/wizard/HelpChangeEmail/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)

            # فحص حالة تسجيل الدخول وطباعة عنوان الصفحة الحالي
            current_title = await page.title()
            logger.info(f"[STEAM_PAGE] Current Page Title: {current_title} | URL: {page.url}")

            # 3. الضغط على الخيار الصحيح لإرسال الكود للإيميل المسجل
            send_code_selector = "a:has-text('Email'), button:has-text('Email'), .help_wizard_button, #email_verification_dialog button"
            send_code_btn = await page.wait_for_selector(send_code_selector, timeout=15000)
            if send_code_btn:
                await send_code_btn.click(force=True)
                logger.info("[STEAM] Clicked 'Email an account verification code'. Waiting for email delivery...")
            else:
                logger.warning("[STEAM:WARN] Could not find send code button. Printing body preview:")
                body_snippet = await page.inner_text("body")
                logger.warning(f"[PAGE_BODY]: {body_snippet[:300].replace(chr(10), ' ')}")

            # ننتظر 10 ثواني كاملة حتى يوصل الإيميل الحقيقي من ستيم للسيرفر
            await page.wait_for_timeout(10000)

            # 4. جلب الكود الحقيقي من xomail
            logger.info(f"Fetching code from xomail for: {orig_email}")
            verification_code = await fetch_code_from_xomail(
                context=context,
                email=orig_email,
                password=email_pass,
                timeout_seconds=60
            )
            logger.info(f"[EXTRACTED_CODE]: {verification_code}")

            # 5. كتابة الكود وتأكيده بصفحة ستيم
            code_selector = "input[name='code'], input[type='text']:visible"
            code_input = await page.wait_for_selector(code_selector, timeout=20000)
            if code_input:
                await code_input.click(force=True)
                await code_input.fill(verification_code)
                await page.keyboard.press("Enter")

            submit_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui, input[type='submit']")
            if submit_btn:
                await submit_btn.click(force=True)

            await page.wait_for_timeout(6000)

            # 6. إدخال الإيميل الجديد
            logger.info(f"Entering new target email: {new_email}")
            new_email_selector = "input#email_input, input#email, input[name='new_email'], input[type='text']:visible"
            new_email_input = await page.wait_for_selector(new_email_selector, timeout=25000)
            if new_email_input:
                await new_email_input.click(force=True)
                await new_email_input.fill("")
                await page.keyboard.type(new_email, delay=40)
                await page.keyboard.press("Enter")

            confirm_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui, button:has-text('Change Email')")
            if confirm_btn:
                await confirm_btn.click(force=True)

            await page.wait_for_timeout(6000)

            # فحص وتأكيد نجاح إرسال كود التأكيد للإيميل الجديد
            status_text = await page.inner_text("body")
            logger.info(f"[STEAM_RESULT]: {status_text[:350].replace(chr(10), ' ')}")

            # 7. مرحلة انتظار الكود الجديد من المستخدم عبر الواجهة
            if self.supabase and account_id:
                logger.info(f"[WAITING] Setting status to 'waiting_code' for record {account_id}...")
                self.supabase.table("stock_accounts").update({
                    "status": "waiting_code",
                    "target_verification_code": None
                }).eq("id", account_id).execute()

                target_code = None
                for _ in range(60):
                    await asyncio.sleep(2)
                    res = self.supabase.table("stock_accounts").select("target_verification_code").eq("id", account_id).execute()
                    if res.data and res.data[0].get("target_verification_code"):
                        target_code = str(res.data[0]["target_verification_code"]).strip()
                        break

                if not target_code:
                    raise TimeoutError("User did not enter target verification code in time.")

                logger.info(f"[RECEIVED] User entered code: {target_code}. Submitting to Steam...")
                final_input = await page.wait_for_selector("input[name='code'], input[type='text']:visible", timeout=15000)
                if final_input:
                    await final_input.click(force=True)
                    await final_input.fill(target_code)
                    await page.keyboard.press("Enter")

                await page.wait_for_timeout(5000)

            logger.info("Email change process fully completed!")
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
