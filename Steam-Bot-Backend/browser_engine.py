import asyncio
import logging
import os
from playwright.async_api import async_playwright
from mail_extractor import MailWorker
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
                    "--disable-gpu",
                    "--disable-features=Translate,OptimizationHints",
                    "--no-zygote",
                    "--single-process"
                ]
            )

    async def _block_heavy_resources(self, page):
        """منع تحميل الصور والخطوط والميديا لتقليل استهلاك الرام ومنع السيرفر من الانهيار"""
        async def route_handler(route):
            if route.request.resource_type in ["image", "media", "font"]:
                await route.abort()
            else:
                await route.continue_()
        await page.route("**/*", route_handler)

    async def _sign_out_everywhere(self, page):
        try:
            logger.info("[LOGOUT] Opening authorized devices to sign out everywhere...")
            await page.goto("https://store.steampowered.com/account/authorizeddevices", wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(1.5)

            sign_out_btn = await page.wait_for_selector("button.btn_red_white_text, button:has-text('Sign out everywhere')", timeout=8000)
            if sign_out_btn:
                await sign_out_btn.click(force=True)
                logger.info("[LOGOUT] Clicked primary button. Confirming modal dialog...")
                await asyncio.sleep(1.2)

                confirm_selectors = [
                    "xpath=//div[contains(@class, 'modal_frame')]//button[contains(., 'Sign out everywhere')]",
                    "xpath=//div[contains(@class, 'newmodal')]//span[contains(., 'Sign out everywhere')]",
                    "xpath=//div[contains(@class, 'newmodal')]//span[contains(., 'OK')]",
                    ".newmodal button:has-text('Sign out everywhere')",
                    ".btn_medium.btn_green_steamui"
                ]

                for c_sel in confirm_selectors:
                    try:
                        modal_btn = await page.query_selector(c_sel)
                        if modal_btn:
                            await modal_btn.click(force=True)
                            logger.info("[LOGOUT:SUCCESS] Confirmed sign-out modal. Sessions revoked.")
                            break
                    except Exception:
                        continue

                await asyncio.sleep(1.5)
        except Exception as e:
            logger.warning(f"[LOGOUT:WARN] Sign out everywhere issue: {str(e)}")

    async def _steam_login_and_request(self, page, steam_user, steam_pass):
        await self._block_heavy_resources(page)
        logger.info("Opening Steam Change Email page...")
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

            await asyncio.sleep(2.5)

        target_button = await page.wait_for_selector(
            "xpath=//a[contains(., 'Email an account verification code')] | //button[contains(., 'Email an account verification code')]",
            timeout=15000
        )
        if target_button:
            await target_button.click(force=True)
            logger.info("[STEAM:SUCCESS] Requested code dispatch to original email.")

    async def execute_task(self, target_dashboard_url: str, task_payload: dict) -> dict:
        await self.initialize()
        context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        page = await context.new_page()

        account_id = task_payload.get("account_id")
        steam_user = task_payload.get("account_identifier")
        steam_pass = task_payload.get("account_secret")
        orig_email = task_payload.get("original_email")
        email_pass = task_payload.get("email_password")
        new_email = task_payload.get("target_contact")

        mail_worker = MailWorker(context, orig_email, email_pass)

        try:
            logger.info("[PARALLEL:START] Starting lightweight parallel execution...")
            await asyncio.gather(
                self._steam_login_and_request(page, steam_user, steam_pass),
                mail_worker.pre_login()
            )

            change_email_code = await mail_worker.fetch_code(timeout_seconds=45)
            logger.info(f"[STEAM_VERIFICATION_CODE]: {change_email_code}")

            # إغلاق صفحة الإيميل فوراً بعد سحب الكود لتفريغ الرام
            await mail_worker.close()

            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(1)

            # إدخال كود التحقق
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
                    el = await page.wait_for_selector(sel, timeout=3000)
                    if el:
                        await el.click(force=True)
                        await el.fill("")
                        await el.fill(change_email_code)
                        await page.keyboard.press("Enter")
                        code_input_filled = True
                        break
                except Exception:
                    continue

            if not code_input_filled:
                raise TimeoutError("Could not locate code input field.")

            await asyncio.sleep(2)

            # إدخال الإيميل الجديد
            logger.info(f"Entering target new email: {new_email}")
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

            await asyncio.sleep(2.5)

            # انتظار كود الواجهة (15 دقيقة)
            if self.supabase and account_id:
                logger.info(f"[WAITING] Waiting for UI confirmation code (15 minutes) for account {account_id}...")
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
                    raise TimeoutError("User did not submit verification code within 15 minutes.")

                logger.info(f"[RECEIVED] Submitting UI code: {user_code}")
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

                await asyncio.sleep(2.5)

            # تسجيل الخروج من كل الأجهزة
            await self._sign_out_everywhere(page)

            logger.info("Pipeline completed successfully! Steam email updated & sessions cleared.")
            return {"status": "success", "message": "Email updated successfully"}

        except Exception as e:
            logger.error(f"Error during browser automation: {str(e)}")
            try:
                await self._sign_out_everywhere(page)
            except Exception:
                pass
            raise e
        finally:
            await mail_worker.close()
            await context.close()

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
