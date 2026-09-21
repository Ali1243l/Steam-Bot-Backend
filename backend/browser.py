import os
import datetime
from playwright.sync_api import sync_playwright

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

def take_snapshot(page, name: str) -> str:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(SCREENSHOTS_DIR, f"{name}_{timestamp}.png")
    try:
        page.screenshot(path=filepath, full_page=True)
        latest_path = os.path.join(SCREENSHOTS_DIR, "latest.png")
        page.screenshot(path=latest_path)
    except Exception as e:
        print(f"[BROWSER] Screenshot capture error: {e}")
    return filepath

class SteamAutomationSession:
    def __init__(self, log_callback=None):
        self.log_callback = log_callback or print
        self.playwright = None
        self.browser = None
        self.page = None

    def log(self, message: str):
        self.log_callback(f"[PIPELINE] {message}")

    def start_email_change_process(self, steam_username: str, steam_password: str, current_email: str, current_email_password: str, new_email: str) -> dict:
        from backend.outlook import extract_steam_code_from_outlook

        self.log(f"Starting headless Chromium session for account: {steam_username}")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )
        context = self.browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        self.page = context.new_page()

        try:
            # 1. Login to Steam
            self.log("[Step 1] Navigating to Steam login page...")
            self.page.goto("https://store.steampowered.com/login/", timeout=45000, wait_until="networkidle")
            take_snapshot(self.page, "01_steam_login_page")

            # Fill username and password
            self.log("[Step 2] Submitting Steam credentials...")
            self.page.locator("input[type='text']").first.fill(steam_username)
            self.page.locator("input[type='password']").fill(steam_password)
            
            # Click explicitly on the Sign in button
            sign_in_btn = self.page.locator("button:has-text('Sign in'), button[type='submit']:has-text('Sign in')").first
            if sign_in_btn.count() > 0:
                sign_in_btn.click()
            else:
                self.page.get_by_role("button", name="Sign in").click()
                
            self.page.wait_for_timeout(6000)
            take_snapshot(self.page, "02_after_login_submit")

            # 2. Go to Steam Account Details
            self.log("[Step 3] Navigating to Steam Account details...")
            self.page.goto("https://store.steampowered.com/account/", timeout=45000)
            self.page.wait_for_timeout(3000)
            take_snapshot(self.page, "03_account_page")

            # 3. Navigate directly to change email wizard
            self.log("[Step 4] Requesting change email wizard...")
            self.page.goto("https://help.steampowered.com/en/wizard/HelpWithLoginInfoReset?issueid=409", timeout=45000)
            self.page.wait_for_timeout(3000)
            take_snapshot(self.page, "04_email_wizard")

            # Click 'Email an account verification code to...'
            self.log("[Step 5] Clicking 'Email verification code' to current Outlook email...")
            self.page.locator("text='Email an account verification code'").click()
            self.page.wait_for_timeout(4000)
            take_snapshot(self.page, "05_code_dispatched_to_outlook")

            # 4. Extract code from Outlook
            self.log(f"[Step 6] Extracting verification code from Outlook ({current_email})...")
            outlook_code = extract_steam_code_from_outlook(current_email, current_email_password, max_wait_sec=50)
            if not outlook_code:
                raise Exception(f"Failed to extract Steam verification code from Outlook for {current_email}")

            self.log(f"[Step 7] Entering Outlook code [{outlook_code}] into Steam...")
            code_input = self.page.locator("input[type='text']").first
            code_input.fill(outlook_code)
            self.page.locator("button:has-text('Continue'), input[type='submit'][value='Continue'], button[type='submit']").first.click()
            self.page.wait_for_timeout(4000)
            take_snapshot(self.page, "06_submitted_outlook_code")

            # 5. Enter New Email Address
            self.log(f"[Step 8] Submitting new target email address: {new_email}...")
            new_email_input = self.page.locator("input[type='email'], input[name='email'], input[type='text']").first
            new_email_input.fill(new_email)
            self.page.locator("button:has-text('Change my email address'), button[type='submit'], input[type='submit']").first.click()
            self.page.wait_for_timeout(4000)
            take_snapshot(self.page, "07_final_code_sent_to_target_email")

            self.log(f"[Step 9] [SUCCESS] Steam has dispatched the final verification code to {new_email}!")
            return {
                "success": True,
                "status": "waiting_code",
                "message": f"Verification code sent to {new_email}. Awaiting input.",
                "target_email": new_email
            }

        except Exception as e:
            self.log(f"[ERROR] Automation failure: {e}")
            if self.page:
                take_snapshot(self.page, "error_failure")
            self.cleanup()
            return {"success": False, "error": str(e)}

    def submit_final_verification_code(self, code: str) -> dict:
        if not self.page:
            return {"success": False, "error": "No active browser session found."}
        try:
            self.log(f"[Step 10] Submitting final verification code [{code}] into Steam...")
            code_input = self.page.locator("input[type='text']").first
            code_input.fill(code)
            self.page.locator("button:has-text('Change my email address'), button[type='submit'], text='Continue'").first.click()
            self.page.wait_for_timeout(5000)
            take_snapshot(self.page, "08_email_change_finalized")

            self.log("[✓] EMAIL CHANGE COMPLETED SUCCESSFULLY!")
            self.cleanup()
            return {"success": True, "status": "completed"}
        except Exception as e:
            self.log(f"[ERROR] Failed to submit final code: {e}")
            self.cleanup()
            return {"success": False, "error": str(e)}

    def cleanup(self):
        try:
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        self.browser = None
        self.page = None
        self.playwright = None
