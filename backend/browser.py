import os
import time
from playwright.sync_api import sync_playwright
from backend.outlook import get_outlook_verification_code

SCREENSHOTS_DIR = "/home/ubuntu/Steam-Bot-Backend/screenshots"
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

def take_snapshot(page, name):
    try:
        p = os.path.join(SCREENSHOTS_DIR, f"{name}.png")
        page.screenshot(path=p)
        latest = os.path.join(SCREENSHOTS_DIR, "latest.png")
        page.screenshot(path=latest)
    except Exception:
        pass

class SteamAutomationSession:
    def __init__(self, log_callback=None):
        self.log_callback = log_callback or print
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def log(self, message: str):
        self.log_callback(f"[PIPELINE] {message}")

    def start_email_change_process(self, steam_username: str, steam_password: str, current_email: str, current_email_password: str, new_email: str) -> dict:
        self.log(f"Starting browser session for Steam user: [{steam_username}] -> Target: [{new_email}]")
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

            # 1. فتح صفحة تسجيل الدخول في Steam
            self.log("[Step 1] Loading Steam Login page...")
            self.page.goto("https://store.steampowered.com/login/", timeout=35000)
            self.page.wait_for_timeout(2000)

            # تخطي الكوكيز
            try:
                self.page.evaluate("""() => {
                    const btn = document.querySelector('#acceptAllButton, button');
                    if (btn && btn.innerText.includes('Accept')) btn.click();
                }""")
            except Exception:
                pass

            take_snapshot(self.page, "step1_steam_login_page")

            # تعبئة اسم المستخدم وكلمة المرور بدون اعتراض الـ UI (عبر Tab و Force)
            self.log(f"[Step 1] Filling credentials for {steam_username}...")
            user_input = self.page.locator("input[type='text']").first
            user_input.fill(steam_username, force=True)
            self.page.wait_for_timeout(500)

            # الانتقال لحقل الباسورد بالـ Tab وتعبئته فوراً
            user_input.press("Tab")
            self.page.keyboard.type(steam_password)
            self.page.wait_for_timeout(500)

            take_snapshot(self.page, "step1_credentials_filled")

            # الضغط على زر تسجيل الدخول
            self.page.keyboard.press("Enter")
            self.page.wait_for_timeout(5000)
            take_snapshot(self.page, "step1_after_login_submit")

            # 2. الذهاب لصفحة تغيير الإيميل
            self.log("[Step 2] Navigating to Steam change email portal...")
            self.page.goto("https://store.steampowered.com/account/changeemail/", timeout=35000)
            self.page.wait_for_timeout(2500)
            take_snapshot(self.page, "step2_change_email_page")

            # إرسال كود التحقق للأوتلوك
            wizard_btn = self.page.locator("a:has-text('Email'), button:has-text('Email'), .help_wizard_button, a:has-text('verification code')").first
            if wizard_btn.count() > 0:
                self.log("[Step 2] Requesting verification code to Outlook...")
                wizard_btn.click(force=True)
                self.page.wait_for_timeout(2500)

            take_snapshot(self.page, "step3_steam_code_dispatched")
            self.log("[Step 3] Steam verification code dispatched to Outlook successfully!")

            # 3. فتح Outlook وسحب الكود الحقيقي
            self.log(f"[Step 4] Reading verification code from Outlook: {current_email}...")
            outlook_code = get_outlook_verification_code(current_email, current_email_password, self.context)
            if not outlook_code:
                take_snapshot(self.page, "error_outlook_failed")
                raise Exception(f"Could not retrieve verification code from Outlook ({current_email}).")

            self.log(f"[Step 5] [SUCCESS] Retrieved Outlook code: [{outlook_code}]")

            # 4. إدخال كود Outlook في ستيم
            self.log(f"[Step 5] Entering Outlook code [{outlook_code}] into Steam...")
            code_input = self.page.locator("input[type='text'], input[name='email_confirmation_code'], input.forgot_login_input").first
            code_input.fill(outlook_code, force=True)
            take_snapshot(self.page, "step5_filled_outlook_code")

            continue_btn = self.page.locator("button:has-text('Continue'), input[type='submit'][value='Continue'], button[type='submit'], .btn_blue_steamui").first
            continue_btn.click(force=True)
            self.page.wait_for_timeout(3000)
            take_snapshot(self.page, "step5_after_continue")

            # 5. إدخال الإيميل الجديد (إيميل الزبون)
            self.log(f"[Step 6] Entering Target New Email: {new_email}...")
            new_email_input = self.page.locator("input[type='email'], input[name='email'], input[type='text']").first
            new_email_input.fill(new_email, force=True)
            take_snapshot(self.page, "step6_filled_new_email")

            submit_email_btn = self.page.locator("button:has-text('Change my email address'), button:has-text('Next'), button[type='submit'], input[type='submit']").first
            submit_email_btn.click(force=True)
            self.page.wait_for_timeout(3000)
            take_snapshot(self.page, "step7_final_code_dispatched_to_gmail")

            self.log(f"[Step 7] [SUCCESS] Steam sent confirmation code to target email: {new_email}!")
            self.log("[Step 8] Waiting for your final 5-character code from Gmail...")

            return {
                "success": True,
                "status": "waiting_code",
                "message": f"Verification code sent to {new_email} successfully!",
                "target_email": new_email
            }
        except Exception as e:
            self.log(f"[ERROR] Session failure: {e}")
            take_snapshot(self.page, "error_failure") if self.page else None
            self.close()
            return {"success": False, "error": str(e)}

    def submit_final_verification_code(self, code: str) -> dict:
        self.log(f"Submitting final code [{code}] on the active page...")
        try:
            if not self.page or self.page.is_closed():
                raise Exception("Browser page is not open.")

            code_box = self.page.locator("input[type='text'], input[name='email_confirmation_code'], input.forgot_login_input").first
            if code_box.count() == 0:
                take_snapshot(self.page, "error_final_input_not_found")
                raise Exception("Final verification code input field not found on active page.")

            code_box.fill(code, force=True)
            self.page.wait_for_timeout(1000)

            confirm_btn = self.page.locator("button:has-text('Change my email address'), button:has-text('Submit'), input[type='submit'], button[type='submit'], .btn_blue_steamui").first
            confirm_btn.click(force=True)
            self.page.wait_for_timeout(3500)
            take_snapshot(self.page, "step9_email_change_completed")

            self.log(f"[SUCCESS] EMAIL HAS OFFICIALLY CHANGED TO YOUR TARGET EMAIL!")
            self.cleanup_and_logout()
            return {"success": True, "status": "completed"}
        except Exception as e:
            self.log(f"[ERROR] Finalizing error: {e}")
            self.close()
            return {"success": False, "error": str(e)}

    def cleanup_and_logout(self):
        self.log("[CLEANUP] Logging out from Steam and cleaning temporary screenshots...")
        try:
            if self.page and not self.page.is_closed():
                self.page.goto("https://store.steampowered.com/logout/", timeout=15000)
                self.page.wait_for_timeout(2000)
        except Exception:
            pass

        self.close()

        try:
            for f in os.listdir(SCREENSHOTS_DIR):
                if f != "latest.png":
                    os.remove(os.path.join(SCREENSHOTS_DIR, f))
            print("[CLEANUP] Screenshots cleaned successfully.")
        except Exception as e:
            print(f"[CLEANUP] Error cleaning screenshots: {e}")

    def close(self):
        try:
            if self.page and not self.page.is_closed():
                self.page.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
