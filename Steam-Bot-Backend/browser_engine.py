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
            await page.goto("https://help.steampowered.com/en/wizard/HelpChangeEmail/", wait_until="domcontentloaded", timeout=45000)

            # تسجيل الدخول إن طُلب
            if "login" in page.url.lower():
                logger.info(f"Steam Help requested login for user: {steam_user}")
                user_selector = "input#input_username, input[type='text']:not([readonly]), input[name='username']"
                await page.wait_for_selector(user_selector, timeout=20000)
                await page.fill(user_selector, steam_user)

                pwd_selector = "input#input_password, input[type='password']:not([readonly]), input[name='password']"
                await page.wait_for_selector(pwd_selector, timeout=15000)
                await page.fill(pwd_selector, steam_pass)
                await page.keyboard.press("Enter")

                await page.wait_for_timeout(3500)

            logger.info(f"Current Help Wizard URL: {page.url}")

            # 2. الضغط على زر إرسال كود التحقق
            target_button = await page.wait_for_selector(
                "xpath=//a[contains(., 'Email an account verification code')] | //button[contains(., 'Email an account verification code')]",
                timeout=15000
            )
            if target_button:
                await target_button.click(force=True)
                logger.info("[STEAM:SUCCESS] Requested verification code dispatch.")

            # مهلة سريعة 5 ثوانٍ فقط لوصول الرسالة
            await page.wait_for_timeout(5000)

            # 3. جلب الكود من بريد xomail
            logger.info(f"Fetching code from xomail for: {orig_email}")
            change_email_code = await fetch_code_from_xomail(
                context=context,
                email=orig_email,
                password=email_pass,
                timeout_seconds=40
            )
            logger.info(f"[STEAM_VERIFICATION_CODE]: {change_email_code}")

            await page.wait_for_load_state("domcontentloaded")

            # 4. كتابة الكود المستلم من xomail وتجنب حقول الـ readonly
            first_code_selector = "input#code, input[name='code'], input[type='text']:not([readonly]):visible"
            await page.wait_for_selector(first_code_selector, timeout=15000)
            await page.fill(first_code_selector, change_email_code)
            await page.keyboard.press("Enter")

            # فحص زر submit احتياطاً
            sub_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui, input[type='submit']")
            if sub_btn:
                try:
                    await sub_btn.click(force=True)
                except Exception:
                    pass

            await page.wait_for_timeout(2500)
            await page.wait_for_load_state("domcontentloaded")

            # 5. كتابة الإيميل الجديد وحفظه
            logger.info(f"Entering target new email: {new_email}")
            new_email_selector = "input#email_input, input#email, input[name='new_email'], input[type='text']:not([readonly]):visible"
            await page.wait_for_selector(new_email_selector, timeout=15000)
            await page.fill(new_email_selector, new_email)
            await page.keyboard.press("Enter")

            confirm_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui, button:has-text('Change Email')")
            if confirm_btn:
                try:
                    await confirm_btn.click(force=True)
                except Exception:
                    pass

            await page.wait_for_timeout(3000)

            # 6. مرحلة انتظار كود الواجهة (المستلم على الإيميل الجديد)
            if self.supabase and account_id:
                logger.info(f"[WAITING] Account {account_id} is waiting for user confirmation code...")
                self.supabase.table("stock_accounts").update({
                    "status": "waiting_code",
                    "target_verification_code": None
                }).eq("id", account_id).execute()

                user_code = None
                # استعلام سريع كل ثانية
                for _ in range(90):
                    await asyncio.sleep(1)
                    res = self.supabase.table("stock_accounts").select("target_verification_code").eq("id", account_id).execute()
                    if res.data and res.data[0].get("target_verification_code"):
                        user_code = str(res.data[0]["target_verification_code"]).strip()
                        break

                if not user_code:
                    raise TimeoutError("User did not submit target verification code in time.")

                logger.info(f"[RECEIVED] User code: {user_code}. Filling into Steam...")
                
                # كتابة الكود الثاني في حقل قابل للكتابة حصراً (not readonly)
                final_code_selector = "input#code, input[name='code'], input[type='text']:not([readonly]):visible"
                await page.wait_for_selector(final_code_selector, timeout=15000)
                await page.fill(final_code_selector, user_code)
                await page.keyboard.press("Enter")

                final_sub = await page.query_selector("button[type='submit'], .btn_blue_steamui")
                if final_sub:
                    try:
                        await final_sub.click(force=True)
                    except Exception:
                    	pass

                await page.wait_for_timeout(3000)

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
