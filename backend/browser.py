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
        self.log(f"Starting browser session for: {steam_username} -> {new_email}")
        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            self.context = self.browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            self.page = self.context.new_page()

            # 1. Login
            self.log("[Step 1] Navigating to Steam login page...")
            self.page.goto("https://store.steampowered.com/login/", timeout=45000)
            self.page.wait_for_timeout(2000)

            self.log("[Step 2] Submitting Steam credentials...")
            self.page.locator("input[type='text']").first.fill(steam_username)
            self.page.locator("input[type='password']").fill(steam_password)
            
            sign_in_btn = self.page.locator("button:has-text('Sign in'), button[type='submit']:has-text('Sign in')").first
            if sign_in_btn.count() > 0:
                sign_in_btn.click()
            else:
                self.page.get_by_role("button", name="Sign in").click()
                
            self.page.wait_for_timeout(3500)
            take_snapshot(self.page, "02_after_login_submit")

            # 2. Account Details
            self.log("[Step 3] Navigating to Steam Account details...")
            self.page.goto("https://store.steampowered.com/account/", timeout=45000)
            self.page.wait_for_timeout(1500)

            # 3. Wizard
            self.log("[Step 4] Requesting change email wizard...")
            self.page.goto("https://help.steampowered.com/en/wizard/HelpWithLoginInfoReset?issueid=409", timeout=45000)
            self.page.wait_for_timeout(1500)

            self.log("[Step 5] Clicking 'Email verification code' to current Outlook email...")
            self.page.locator("text='Email an account verification code'").click()
            self.page.wait_for_timeout(2000)
            take_snapshot(self.page, "05_code_dispatched_to_outlook")

            # 4. Extract Outlook Code
            self.log(f"[Step 6] Extracting code from Outlook: {current_email}...")
            outlook_code = get_outlook_verification_code(current_email, current_email_password)
            if not outlook_code:
                raise Exception("Failed to retrieve code from Outlook inbox within timeout.")
            self.log(f"[Step 7] Outlook verification code retrieved: [{outlook_code}]")

            # Enter Outlook Code
            code_input = self.page.locator("input[type='text']").first
            code_input.fill(outlook_code)
            self.page.locator("button:has-text('Continue'), input[type='submit'][value='Continue'], button[type='submit']").first.click()
            self.page.wait_for_timeout(2000)

            # 5. Enter New Email Address
            self.log(f"[Step 8] Entering New Email Address: {new_email}...")
            new_email_input = self.page.locator("input[type='email'], input[name='email'], input[type='text']").first
            new_email_input.fill(new_email)
            self.page.locator("button:has-text('Change my email address'), button[type='submit'], input[type='submit']").first.click()
            self.page.wait_for_timeout(2500)
            take_snapshot(self.page, "07_final_code_sent_to_target_email")

            self.log(f"[Step 9] [SUCCESS] Steam sent final verification code to {new_email}!")
            self.log("[Step 10] Browser is KEEPING the page open waiting for your 5-character code...")

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
        self.log(f"Entering final code [{code}] on the ACTIVE Steam page...")
        try:
            if not self.page or self.page.is_closed():
                raise Exception("Browser page is not open.")

            # ابحث عن خانة الكود في نفس الصفحة المفتوحة
            code_box = self.page.locator("input[type='text'], input[name='email_confirmation_code'], input.forgot_login_input").first
            if code_box.count() == 0:
                take_snapshot(self.page, "error_final_input_not_found")
                raise Exception("Final verification code input field not found on active page.")

            code_box.fill(code)
            self.page.wait_for_timeout(500)

            # الضغط على زر تأكيد تغيير الإيميل
            confirm_btn = self.page.locator("button:has-text('Change my email address'), button:has-text('Submit'), input[type='submit'], button[type='submit']").first
            confirm_btn.click()
            self.page.wait_for_timeout(3000)
            take_snapshot(self.page, "08_email_change_completed")

            self.log(f"[SUCCESS] EMAIL HAS OFFICIALLY CHANGED TO YOUR TARGET EMAIL!")
            self.close()
            return {"success": True, "status": "completed"}
        except Exception as e:
            self.log(f"[ERROR] Finalizing error: {e}")
            self.close()
            return {"success": False, "error": str(e)}

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
