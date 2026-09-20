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
            # 1. التوجه لصفحة تغيير الإيميل
            logger.info("Opening Steam Help Change Email page directly...")
            await page.goto("https://help.steampowered.com/en/wizard/HelpChangeEmail/", wait_until="domcontentloaded", timeout=35000)

            if "login" in page.url.lower():
                logger.info(f"Steam login requested for: {steam_user}")
                user_selector = "input#input_username, input[name='username'], input[type='text']:not([readonly])"
                await page.wait_for_selector(user_selector, timeout=15000)
                await page.fill(user_selector, steam_user)

                pwd_selector = "input#input_password, input[name='password'], input[type='password']:not([readonly])"
                await page.wait_for_selector(pwd_selector, timeout=10000)
                await page.fill(pwd_selector, steam_pass)
                await page.keyboard.press("Enter")

                await page.wait_for_timeout(3000)

            # 2. الضغط على زر إرسال الكود للإيميل الأصلي
            target_button = await page.wait_for_selector(
                "xpath=//a[contains(., 'Email an account verification code')] | //button[contains(., 'Email an account verification code')]",
                timeout=15000
            )
            if target_button:
                await target_button.click(force=True)
                logger.info("[STEAM:SUCCESS] Requested code dispatch to original email.")

            # انتظار تحويل صفحة ستيم لنموذج إدخال الكود
            await page.wait_for_timeout(3000)

            # 3. جلب الكود الأحدث من xomail
            change_email_code = await fetch_code_from_xomail(
                context=context,
                email=orig_email,
                password=email_pass,
                timeout_seconds=30
            )
            logger.info(f"[STEAM_VERIFICATION_CODE]: {change_email_code}")

            # التأكد من تحميل صفحة إدخال الكود
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(1500)

            # 4. إدخال الكود عبر عدة محددات مرنة وشاملة
            code_selectors = [
                "input#email_reset_code",
                "input[name='code']",
                "input#code",
                "form#wizard_contents input[type='text']:not([readonly])",
                "xpath=//input[@type='text' and not(@readonly)]"
            ]
            
            code_input_filled = False
            for sel in code_selectors:
                try:
                    el = await page.wait_for_selector(sel, timeout=4000)
                    if el:
                        await el.click(force=True)
                        await el.fill("")
                        await el.fill(change_email_code)
                        await page.keyboard.press("Enter")
                        code_input_filled = True
                        logger.info(f"[STEAM] Successfully filled code using selector: {sel}")
                        break
                except Exception:
                    continue

            if not code_input_filled:
                raise TimeoutError("Could not locate the editable verification code input field.")

            # محاولة نقر زر المتابعة إن لم يكتفِ بـ Enter
            continue_btn = await page.query_selector("input[type='submit'], button[type='submit'], .btn_blue_steamui, button:has-text('Continue')")
            if continue_btn:
                try:
                    await continue_btn.click(force=True)
                except Exception:
                    pass

            await page.wait_for_timeout(3000)

            # 5. كتابة الإيميل الجديد
            logger.info(f"Entering new target email: {new_email}")
            new_email_selector = "input#email_input, input#email, input[name='new_email'], input[type='text']:not([readonly]):visible"
            new_email_input = await page.wait_for_selector(new_email_selector, timeout=20000)
            await new_email_input.click(force=True)
            await new_email_input.fill("")
            await new_email_input.fill(new_email)
            await page.keyboard.press("Enter")

            confirm_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui, button:has-text('Change Email')")
            if confirm_btn:
                try:
                    await confirm_btn.click(force=True)
                except Exception:
                    pass

            await page.wait_for_timeout(3000)

            # 6. مرحلة انتظار كود الواجهة مع مهلة 15 دقيقة (900 ثانية)
            if self.supabase and account_id:
                logger.info(f"[WAITING] Waiting for user input from UI (Timeout: 15 minutes) for account {account_id}...")
                self.supabase.table("stock_accounts").update({
                    "status": "waiting_code",
                    "target_verification_code": None
                }).eq("id", account_id).execute()

                user_code = None
                for _ in range(900):
                    await asyncio.sleep(1)
                    res = self.supabase.table("stock_accounts").select("target_verification_code").eq("id", account_id).execute()
                    if res.data and res.data[0].get("target_verification_code"):
                        user_code = str(res.data[0]["target_verification_code"]).strip()
                        break

                if not user_code:
                    logger.warning("[TIMEOUT] 15 minutes exceeded without user input. Cancelling task.")
                    raise TimeoutError("User did not submit verification code within 15 minutes.")

                logger.info(f"[RECEIVED] User code received: {user_code}. Submitting to Steam...")
                final_input_selector = "input#email_reset_code, input#code, input[name='code'], input[type='text']:not([readonly]):visible"
                final_input = await page.wait_for_selector(final_input_selector, timeout=15000)
                await final_input.click(force=True)
                await final_input.fill(user_code)
                await page.keyboard.press("Enter")

                final_sub = await page.query_selector("button[type='submit'], .btn_blue_steamui")
                if final_sub:
                    try:
                        await final_sub.click(force=True)
                    except Exception:
                        pass

                await page.wait_for_timeout(3000)

            # 7. تسجيل الخروج الشامل بعد اكتمال العملية بنجاح
            await self._sign_out_everywhere(page)

            logger.info("Process finished successfully! Steam email updated & sessions cleared.")
            return {"status": "success", "message": "Email updated successfully"}

        except Exception as e:
            logger.error(f"Error during browser automation: {str(e)}")
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
