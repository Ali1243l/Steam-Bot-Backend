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
                    "--disable-gpu"
                ]
            )
            logger.info("[WARM:SUCCESS] Browser engine warmed up and permanently idle in RAM.")

    async def _block_media(self, page):
        async def route_handler(route):
            if route.request.resource_type in ["image", "media", "font"]:
                await route.abort()
            else:
                await route.continue_()
        await page.route("**/*", route_handler)

    async def _sign_out_everywhere(self, page):
        try:
            logger.info("[LOGOUT] Revoking all devices and active sessions...")
            await page.goto("https://store.steampowered.com/account/authorizeddevices", wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(1)

            sign_out_btn = await page.wait_for_selector("button.btn_red_white_text, button:has-text('Sign out everywhere')", timeout=8000)
            if sign_out_btn:
                await sign_out_btn.click(force=True)
                await asyncio.sleep(1)

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
                            logger.info("[LOGOUT:SUCCESS] All authorized sessions cleared.")
                            break
                    except Exception:
                        continue
                await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"[LOGOUT:WARN] Could not sign out everywhere: {str(e)}")

    async def execute_task(self, target_dashboard_url: str, task_payload: dict) -> dict:
        if not self.browser:
            await self.initialize()

        context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        page = await context.new_page()
        await self._block_media(page)

        account_id = task_payload.get("account_id")
        steam_user = task_payload.get("account_identifier")
        steam_pass = task_payload.get("account_secret")
        orig_email = task_payload.get("original_email")
        email_pass = task_payload.get("email_password")
        new_email = task_payload.get("target_contact")

        mail_worker = MailWorker(context, orig_email, email_pass)

        try:
            logger.info("Directly opening Steam Change Email page...")
            await page.goto("https://help.steampowered.com/en/wizard/HelpChangeEmail/", wait_until="domcontentloaded", timeout=30000)

            if "login" in page.url.lower():
                logger.info(f"Steam login: {steam_user}")
                await page.fill("input#input_username, input[name='username']", steam_user)
                await page.fill("input#input_password, input[name='password']", steam_pass)
                await page.keyboard.press("Enter")
                await asyncio.sleep(2)

            # طلب الكود
            btn = await page.wait_for_selector(
                "xpath=//a[contains(., 'Email an account verification code')] | //button[contains(., 'Email an account verification code')]",
                timeout=12000
            )
            if btn:
                await btn.click(force=True)
                logger.info("[STEAM:SUCCESS] Code dispatched.")

            # جلب الكود السريع
            change_email_code = await mail_worker.fetch_code(timeout_seconds=40)
            logger.info(f"[STEAM_VERIFICATION_CODE]: {change_email_code}")
            await mail_worker.close()

            await asyncio.sleep(1)

            # كتابة الكود الأول
            code_selectors = [
                "input#email_reset_code",
                "input[name='code']",
                "input#code",
                "xpath=//input[@type='text' and not(@readonly)]"
            ]
            for sel in code_selectors:
                try:
                    el = await page.wait_for_selector(sel, timeout=3000)
                    if el:
                        await el.click(force=True)
                        await el.fill("")
                        await el.fill(change_email_code)
                        await page.keyboard.press("Enter")
                        break
                except Exception:
                    continue

            await asyncio.sleep(1.5)

            # كتابة الإيميل الجديد
            new_input = await page.wait_for_selector("input#email_input, input#email, input[name='new_email']", timeout=15000)
            await new_input.fill(new_email)
            await page.keyboard.press("Enter")

            confirm = await page.query_selector("button[type='submit'], .btn_blue_steamui, button:has-text('Change Email')")
            if confirm:
                try:
                    await confirm.click(force=True)
                except Exception:
                    pass

            await asyncio.sleep(2)

            # انتظار كود الواجهة
            if self.supabase and account_id:
                logger.info(f"[WAITING] Waiting for target code from UI for account {account_id}...")
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
                    raise TimeoutError("Timeout: User did not submit code.")

                logger.info(f"[RECEIVED] Submitting code: {user_code}")
                fin_input = await page.wait_for_selector("input#email_reset_code, input#code, input[name='code']", timeout=15000)
                await fin_input.fill(user_code)
                await page.keyboard.press("Enter")

                fin_btn = await page.query_selector("button[type='submit'], .btn_blue_steamui")
                if fin_btn:
                    try:
                        await fin_btn.click(force=True)
                    except Exception:
                        pass
                await asyncio.sleep(2)

            await self._sign_out_everywhere(page)
            logger.info("Pipeline completed successfully!")
            return {"status": "success"}

        finally:
            await mail_worker.close()
            await context.close()

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
