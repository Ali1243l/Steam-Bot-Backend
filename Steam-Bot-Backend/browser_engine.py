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

    async def _sign_out_everywhere(self, page):
        try:
            logger.info("[LOGOUT] Navigating to authorized devices to sign out everywhere...")
            await page.goto("https://store.steampowered.com/account/authorizeddevices", wait_until="domcontentloaded", timeout=15000)
            sign_out_btn = await page.wait_for_selector("button:has-text('Sign out everywhere'), .btn_red_white_text", timeout=8000)
            if sign_out_btn:
                await sign_out_btn.click(force=True)
                logger.info("[LOGOUT:SUCCESS] Successfully signed out of all devices/sessions.")
                await page.wait_for_timeout(1500)
        except Exception as e:
            logger.warning(f"[LOGOUT:WARN] Could not perform sign out everywhere: {str(e)}")

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
            # 1. التوجه مباشرة وبسرعة لصفحة المساعدة
            logger.info("Opening Steam Help Change Email page directly...")
            await page.goto("https://help.steampowered.com/en/wizard/HelpChangeEmail/", wait_until="domcontentloaded", timeout=35000)

            if "login" in page.url.lower():
                logger.info(f"Steam login requested for: {steam_user}")
                user_selector = "input#input_username, input[type='text']:not([readonly]), input[name='username']"
                await page.wait_for_selector(user_selector, timeout=15000)
                await page.fill(user_selector, steam_user)

                pwd_selector = "input#input_password, input[type='password']:not([readonly]), input[name='password']"
                await page.wait_for_selector(pwd_selector, timeout=10000)
                await page.fill(pwd_selector, steam_pass)
                await page.keyboard.press("Enter")

                await page.wait_for_timeout(2500)

            # 2. الضغط السريع على خيار إرسال الكود
            target_button = await page.wait_for_selector(
                "xpath=//a[contains(., 'Email an account verification code')] | //button[contains(., 'Email an account verification code')]",
                timeout=15000
            )
            if target_button:
                await target_button.click(force=True)
                logger.info("[STEAM:SUCCESS] Requested code dispatch to original email.")

            # مهلة 4 ثوانٍ فقط لوصول الرسالة
            await page.wait_for_timeout(4000)

            # 3. جلب الكود الأحدث من xomail
            change_email_code = await fetch_code_from_xomail(
                context=context,
                email=orig_email,
                password=email_pass,
                timeout_seconds=30
            )
            logger.info(f"[STEAM_VERIFICATION_CODE]: {change_email_code}")

            # 4. إدخال الكود الأول بمرونة وتجاوز أي حقول مقفولة
            code_selector = "input#code, input[name='code'], input[type='text']:not([readonly]):visible"
            code_input = await page.wait_for_selector(code_selector, timeout=15000)
            await code_input.fill(change_email_code)
            await page.keyboard.press("Enter")

            # فحص زر التأكيد في حال لم يعمل Enter
            submit_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui, input[type='submit']")
            if submit_btn:
                try:
                    await submit_btn.click(force=True)
                except Exception:
                    pass

            await page.wait_for_timeout(2000)

            # 5. إدخال الإيميل الجديد
            logger.info(f"Entering new target email: {new_email}")
            new_email_selector = "input#email_input, input#email, input[name='new_email'], input[type='text']:not([readonly]):visible"
            new_email_input = await page.wait_for_selector(new_email_selector, timeout=15000)
            await new_email_input.fill(new_email)
            await page.keyboard.press("Enter")

            confirm_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui, button:has-text('Change Email')")
            if confirm_btn:
                try:
                    await confirm_btn.click(force=True)
                except Exception:
                    pass

            await page.wait_for_timeout(2000)

            # 6. مرحلة انتظار كود الواجهة مع مهلة 15 دقيقة (900 ثانية)
            if self.supabase and account_id:
                logger.info(f"[WAITING] Waiting for user input from UI (Timeout: 15 minutes) for account {account_id}...")
                self.supabase.table("stock_accounts").update({
                    "status": "waiting_code",
                    "target_verification_code": None
                }).eq("id", account_id).execute()

                user_code = None
                # حلقة فحص كل ثانية لمدة 15 دقيقة (900 محاولة)
                for second in range(900):
                    await asyncio.sleep(1)
                    res = self.supabase.table("stock_accounts").select("target_verification_code").eq("id", account_id).execute()
                    if res.data and res.data[0].get("target_verification_code"):
                        user_code = str(res.data[0]["target_verification_code"]).strip()
                        break

                if not user_code:
                    logger.warning("[TIMEOUT] 15 minutes exceeded without user input. Cancelling task.")
                    raise TimeoutError("User did not submit verification code within 15 minutes.")

                logger.info(f"[RECEIVED] User code received: {user_code}. Submitting to Steam...")
                final_input = await page.wait_for_selector("input#code, input[name='code'], input[type='text']:not([readonly]):visible", timeout=15000)
                await final_input.fill(user_code)
                await page.keyboard.press("Enter")

                final_sub = await page.query_selector("button[type='submit'], .btn_blue_steamui")
                if final_sub:
                    try:
                        await final_sub.click(force=True)
                    except Exception:
                        pass

                await page.wait_for_timeout(3000)

            # 7. تسجيل الخروج من كل الأجهزة بعد اكتمال المهمة بنجاح
            await self._sign_out_everywhere(page)

            logger.info("Process finished successfully! Steam email updated & sessions cleared.")
            return {"status": "success", "message": "Email updated successfully"}

        except Exception as e:
            logger.error(f"Error during browser automation: {str(e)}")
            # محاولة تسجيل خروج عند حدوث أي خطأ أيضاً
            try:
                await self._sign_out_everywhere(page)
            except Exception:
                pass
            raise e
        finally:
            await context.close()

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
