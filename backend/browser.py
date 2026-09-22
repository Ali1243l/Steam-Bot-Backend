import os
import time
import re
from playwright.sync_api import sync_playwright
from backend.outlook import get_outlook_verification_code

SCREENSHOTS_DIR = "/home/ubuntu/Steam-Bot-Backend/screenshots"
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

def take_snapshot(page, name: str):
    try:
        path = os.path.join(SCREENSHOTS_DIR, f"{name}.png")
        page.screenshot(path=path)
        page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "latest.png"))
        print(f"[SCREENSHOT] Saved: {name}.png", flush=True)
    except Exception as e:
        print(f"[SCREENSHOT_ERR] Could not take {name}: {e}", flush=True)

class SteamAutomationSession:
    def __init__(self, log_callback=None):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.log_callback = log_callback

    def log(self, msg: str, level: str = "info"):
        print(f"[BOT] {msg}", flush=True)
        if self.log_callback:
            try:
                self.log_callback(msg, level)
            except Exception:
                pass

    def start_email_change_process(self, steam_username: str, steam_password: str, current_email: str, current_email_password: str, new_email: str) -> dict:
        self.log(f"Starting Steam automation for: [{steam_username}] -> Target: [{new_email}]")
        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--window-size=1280,900"]
            )
            self.context = self.browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            self.page = self.context.new_page()

            # الخطوة 1: الدخول لصفحة ستيم
            self.log("[Step 1] Loading Steam Login page...")
            self.page.goto("https://store.steampowered.com/login/", timeout=40000)
            self.page.wait_for_timeout(2000)

            # تخطي زر ملفات تعريف الارتباط
            try:
                cookie_btn = self.page.locator("#acceptAllButton, button:has-text('Accept')").first
                if cookie_btn.count() > 0 and cookie_btn.is_visible():
                    cookie_btn.click()
            except Exception:
                pass

            take_snapshot(self.page, "step1_steam_login_page")

            # إدخال اليوزر والباسورد والضغط الفعلي على زر Sign In
            self.log(f"[Step 1] Filling credentials for {steam_username}...")
            user_input = self.page.locator("input[type='text']").first
            user_input.wait_for(state="visible", timeout=10000)
            user_input.fill(steam_username)

            pass_input = self.page.locator("input[type='password']").first
            pass_input.wait_for(state="visible", timeout=10000)
            pass_input.fill(steam_password)

            take_snapshot(self.page, "step1_credentials_filled")

            # الضغط المباشر على زر تسجيل الدخول
            self.log("[Step 1] Clicking Sign In button...")
            sign_in_btn = self.page.locator("button[type='submit']:has-text('Sign In'), button:has-text('Sign In'), button[type='submit']").first
            if sign_in_btn.count() > 0:
                sign_in_btn.click()
            else:
                pass_input.press("Enter")

            # الانتظار حتى تسجيل الدخول أو طلب ستيم جارد
            self.page.wait_for_timeout(6000)
            take_snapshot(self.page, "step1_after_login_submit")

            # التحقق هل طلب ستيم جارد للدخول
            content = self.page.content()
            if "Steam Guard" in content or "code" in content.lower():
                self.log("[Steam Guard] Steam requested verification code for login! Fetching from Outlook...")
                guard_code = get_outlook_verification_code(current_email, current_email_password, self.context)
                if guard_code:
                    self.log(f"[Steam Guard] Entering code: {guard_code}")
                    guard_input = self.page.locator("input[type='text']").first
                    if guard_input.count() > 0:
                        guard_input.fill(guard_code)
                        self.page.keyboard.press("Enter")
                        self.page.wait_for_timeout(5000)
                        take_snapshot(self.page, "step1_guard_submitted")

            # الخطوة 2: الانتقال لصفحة تغيير الإيميل
            self.log("[Step 2] Navigating to Steam change email portal...")
            self.page.goto("https://store.steampowered.com/account/changeemail/", timeout=40000)
            self.page.wait_for_timeout(3000)
            take_snapshot(self.page, "step2_change_email_page")

            # الضغط على زر إرسال كود التحقق
            wizard_btn = self.page.locator("a:has-text('Email'), button:has-text('Email'), .help_wizard_button, a:has-text('verification code')").first
            if wizard_btn.count() > 0:
                self.log("[Step 2] Requesting verification code to Outlook...")
                wizard_btn.click(force=True)
                self.page.wait_for_timeout(3000)

            take_snapshot(self.page, "step3_steam_code_dispatched")
            self.log("[Step 3] Steam verification code dispatched to Outlook!")

            # الخطوة 3: استخراج الكود من Outlook
            self.log(f"[Step 4] Reading verification code from Outlook ({current_email})...")
            outlook_code = get_outlook_verification_code(current_email, current_email_password, self.context)
            if not outlook_code:
                take_snapshot(self.page, "error_outlook_failed")
                raise Exception(f"Could not retrieve verification code from Outlook ({current_email}).")

            self.log(f"[Step 5] [SUCCESS] Retrieved Outlook code: [{outlook_code}]")

            # إدخال الكود في ستيم
            code_input = self.page.locator("input[type='text'], input[name='email_confirmation_code'], input.forgot_login_input").first
            code_input.fill(outlook_code, force=True)
            take_snapshot(self.page, "step5_filled_outlook_code")

            continue_btn = self.page.locator("button:has-text('Continue'), input[type='submit'][value='Continue'], button[type='submit'], .btn_blue_steamui").first
            continue_btn.click(force=True)
            self.page.wait_for_timeout(3000)
            take_snapshot(self.page, "step5_after_continue")

            # إدخال إيميل الزبون الجديد
            self.log(f"[Step 6] Entering Target New Email: {new_email}...")
            new_email_input = self.page.locator("input[type='email'], input[name='email'], input[type='text']").first
            new_email_input.fill(new_email, force=True)
            take_snapshot(self.page, "step6_filled_new_email")

            submit_email_btn = self.page.locator("button:has-text('Change my email address'), button:has-text('Next'), button[type='submit'], input[type='submit']").first
            submit_email_btn.click(force=True)
            self.page.wait_for_timeout(3000)
            take_snapshot(self.page, "step7_waiting_customer_verification")

            self.log(f"[Step 7] [SUCCESS] Verification email dispatched to Customer: {new_email}!")
            return {"success": True, "status": "waiting_code", "message": f"Waiting for verification code from customer {new_email}"}

        except Exception as e:
            self.log(f"Automation Exception: {str(e)}", "error")
            if self.page:
                take_snapshot(self.page, "crash_exception")
            return {"success": False, "error": str(e)}

    def finalize_with_code(self, code: str) -> dict:
        try:
            if not self.page:
                return {"success": False, "error": "No active browser session"}
            self.log(f"Entering Customer code: [{code}]...")
            code_input = self.page.locator("input[type='text']").first
            code_input.fill(code, force=True)
            self.page.keyboard.press("Enter")
            self.page.wait_for_timeout(5000)
            take_snapshot(self.page, "final_email_changed")
            return {"success": True, "message": "Email successfully changed!"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def close(self):
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
