import re
import time
import os

SCREENSHOTS_DIR = "/home/ubuntu/Steam-Bot-Backend/screenshots"

def take_snap(page, name):
    try:
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        page.screenshot(path=os.path.join(SCREENSHOTS_DIR, f"{name}.png"))
    except Exception:
        pass

def extract_steam_code(text: str) -> str:
    # البحث فقط عن كود ستيم الحقيقي بجانب الكلمات الدالة
    patterns = [
        r'(?:verification code|confirmation code|security code)[^A-Z0-9]*([A-Z0-9]{5})\b',
        r'Steam Support[^A-Z0-9]*([A-Z0-9]{5})\b',
        r'([A-Z0-9]{5})\s*(?:is your Steam|to verify)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            c = m.group(1).upper()
            if c not in ["STEAM", "VALVE", "HTTPS", "LOGIN", "INBOX"]:
                return c
    return None

def get_outlook_verification_code(email_address: str, email_password: str, browser_context, max_wait_seconds: int = 40) -> str:
    print(f"[OUTLOOK-DYNAMIC] Logging into Outlook for: {email_address}...")
    page = browser_context.new_page()
    try:
        page.goto("https://login.live.com/", timeout=30000)
        page.wait_for_timeout(1000)

        # 1. إدخال الإيميل
        email_input = page.locator("#i0116, input[type='email'], input[name='loginfmt']").first
        email_input.wait_for(state="visible", timeout=15000)
        email_input.fill(email_address)
        take_snap(page, "outlook_01_email")

        next_btn = page.locator("#idSIButton9, input[type='submit'], button[type='submit']").first
        if next_btn.count() > 0 and next_btn.is_visible():
            next_btn.click()
        else:
            email_input.press("Enter")
        page.wait_for_timeout(2000)

        # 2. إدخال الباسورد
        pass_input = page.locator("#i0118, input[type='password'], input[name='passwd']").first
        pass_input.wait_for(state="visible", timeout=15000)
        pass_input.fill(email_password)
        take_snap(page, "outlook_02_password")

        sign_btn = page.locator("#idSIButton9, input[type='submit'], button[type='submit']").first
        if sign_btn.count() > 0 and sign_btn.is_visible():
            sign_btn.click()
        else:
            pass_input.press("Enter")
        page.wait_for_timeout(2500)

        # 3. تخطي الشاشات الترويجية
        for _ in range(2):
            confirm_btn = page.locator("#idSIButton9, button:has-text('Yes'), button:has-text('No'), input[value='Yes'], input[value='No']").first
            if confirm_btn.count() > 0 and confirm_btn.is_visible():
                confirm_btn.click()
                page.wait_for_timeout(2000)

        take_snap(page, "outlook_03_logged_in")

        # 4. فتح صندوق الوارد
        print("[OUTLOOK-DYNAMIC] Opening Outlook Inbox...")
        page.goto("https://outlook.live.com/mail/0/inbox", timeout=30000)
        page.wait_for_timeout(2500)
        take_snap(page, "outlook_04_inbox")

        start_time = time.time()
        while time.time() - start_time < max_wait_seconds:
            page.wait_for_timeout(2000)

            # التبديل بين تبويب Focused و تبويب Other (أو Junk)
            other_tab = page.locator("button:has-text('Other'), button:has-text('其他'), div[role='tab']:has-text('其他')").first
            if other_tab.count() > 0 and other_tab.is_visible():
                other_tab.click()
                page.wait_for_timeout(1000)

            # البحث عن رسالة ستيم
            # 1. التبديل إلى تبويب 'Other / 其他' إذا كان Focused فارغاً
            other_tab = page.locator("button:has-text('Other'), button:has-text('其他'), div[role='tab']:has-text('Other'), div[role='tab']:has-text('其他')").first
            if other_tab.count() > 0 and other_tab.is_visible():
                try:
                    other_tab.click()
                    page.wait_for_timeout(1500)
                except Exception:
                    pass

            # 2. البحث عن رسالة ستيم
            steam_item = page.locator("div[role='option']:has-text('Steam'), div:has-text('Steam Support'), span:has-text('Steam')").first
            if steam_item.count() == 0:
                # محاولة فحص مجلد Junk / 垃圾邮件 إذا لم توجد
                junk = page.locator("div[title*='Junk'], span:has-text('Junk'), span:has-text('垃圾邮件')").first
                if junk.count() > 0:
                    try:
                        junk.click()
                        page.wait_for_timeout(2000)
                        steam_item = page.locator("div[role='option']:has-text('Steam'), span:has-text('Steam')").first
                    except Exception:
                        pass
            if steam_item.count() > 0:
                print("[OUTLOOK-DYNAMIC] Real Steam email spotted! Clicking...")
                steam_item.click()
                page.wait_for_timeout(2000)
                take_snap(page, "outlook_05_steam_opened")

                reading_pane = page.locator("div[role='main'], div.ReadingPaneContainer, div[aria-label='Reading Pane']").first
                body = reading_pane.inner_html() if reading_pane.count() > 0 else page.content()
                
                code = extract_steam_code(body)
                if code:
                    print(f"[OUTLOOK-DYNAMIC] [SUCCESS] Real Steam Verification Code: [{code}]")
                    page.close()
                    return code

            print("[OUTLOOK-DYNAMIC] Waiting for Steam email to land...")

        take_snap(page, "outlook_error_timeout")
        page.close()
    except Exception as e:
        print(f"[OUTLOOK-DYNAMIC] Error: {e}")
        take_snap(page, "outlook_exception")
        try:
            page.close()
        except Exception:
            pass

    return None

def extract_steam_code_from_outlook(email_user: str, email_pass: str, max_wait_sec: int = 60) -> str | None:
    return None
