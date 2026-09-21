import poplib
import imaplib
import email
import re
import time
from playwright.sync_api import sync_playwright

def get_code_via_pop3(email_address: str, email_password: str) -> str:
    try:
        pop = poplib.POP3_SSL("outlook.office365.com", 995, timeout=10)
        pop.user(email_address)
        pop.pass_(email_password)
        num_messages = len(pop.list()[1])
        if num_messages > 0:
            for i in range(num_messages, max(0, num_messages - 5), -1):
                raw = b"\n".join(pop.retr(i)[1]).decode(errors="ignore")
                if "Steam" in raw:
                    matches = re.findall(r'\b[A-Z0-9]{5}\b', raw)
                    for m in matches:
                        if m not in ["STEAM", "VALVE", "HTTPS", "LOGIN"]:
                            pop.quit()
                            return m
        pop.quit()
    except Exception as e:
        print(f"[POP3] Notice: {e}")
    return None

def get_code_via_browser(browser_context, email_address: str, email_password: str) -> str:
    print(f"[OUTLOOK-WEB] Logging in via headless browser: {email_address}...")
    page = browser_context.new_page()
    try:
        page.goto("https://outlook.live.com/mail/0/", timeout=30000)
        page.wait_for_timeout(2000)

        # Login flow
        if "login.live.com" in page.url or page.locator("input[type='email']").count() > 0:
            page.locator("input[type='email']").fill(email_address)
            page.locator("button:has-text('Next'), input[type='submit']").click()
            page.wait_for_timeout(2000)

            page.locator("input[type='password']").fill(email_password)
            page.locator("button:has-text('Sign in'), input[type='submit']").click()
            page.wait_for_timeout(2500)

            # Stay signed in prompt?
            if page.locator("button:has-text('Yes'), input[type='submit']").count() > 0:
                page.locator("button:has-text('Yes'), input[type='submit']").first.click()
                page.wait_for_timeout(2500)

        # Look for Steam email in list
        print("[OUTLOOK-WEB] Reading inbox list...")
        steam_item = page.locator("span:has-text('Steam'), div:has-text('Steam Support')").first
        if steam_item.count() > 0:
            steam_item.click()
            page.wait_for_timeout(2000)

            text_content = page.content()
            matches = re.findall(r'\b[A-Z0-9]{5}\b', text_content)
            for m in matches:
                if m not in ["STEAM", "VALVE", "HTTPS", "LOGIN", "INBOX"]:
                    print(f"[OUTLOOK-WEB] Found code: {m}")
                    page.close()
                    return m
        page.close()
    except Exception as e:
        print(f"[OUTLOOK-WEB] Error reading web inbox: {e}")
        try:
            page.close()
        except Exception:
            pass
    return None

def get_outlook_verification_code(email_address: str, email_password: str, browser_context=None, max_attempts: int = 8) -> str:
    print(f"[OUTLOOK] Checking inbox for: {email_address} (Universal Method)...")
    for attempt in range(max_attempts):
        # 1. Try POP3 first (fastest, takes 1 second)
        code = get_code_via_pop3(email_address, email_password)
        if code:
            print(f"[OUTLOOK] Successfully extracted via POP3: [{code}]")
            return code

        time.sleep(2)

    # 2. If POP3 fails, fallback to web-based extraction if browser context is passed
    if browser_context:
        web_code = get_code_via_browser(browser_context, email_address, email_password)
        if web_code:
            return web_code

    return None
