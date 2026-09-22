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

def extract_code_from_text(text: str) -> str:
    matches = re.findall(r'\b[A-Z0-9]{5}\b', text)
    blacklist = {"STEAM", "VALVE", "HTTPS", "LOGIN", "INBOX", "ENTER", "CLICK", "RESET", "HELP1", "ERROR", "AGREE", "ABOUT", "TERMS"}
    # نفضل الكود الذي يجمع بين الحروف والأرقام
    for m in matches:
        if m not in blacklist and any(c.isdigit() for c in m) and any(c.isalpha() for c in m):
            return m
    for m in matches:
        if m not in blacklist:
            return m
    return None

def get_outlook_verification_code(email_address: str, email_password: str, browser_context, max_wait_seconds: int = 40) -> str:
    print(f"[OUTLOOK-DYNAMIC] Starting login for: {email_address}...")
    page = browser_context.new_page()
    try:
        page.goto("https://login.live.com/", timeout=30000)
        page.wait_for_timeout(1000)

        # 1. إدخال الإيميل (معرف مايكروسوفت الرسمي #i0116 أو أي حقل إيميل)
        print("[OUTLOOK-DYNAMIC] Entering email...")
        email_input = page.locator("#i0116, input[type='email'], input[name='loginfmt']").first
        email_input.wait_for(state="visible", timeout=15000)
        email_input.fill(email_address)
        take_snap(page, "outlook_01_email_entered")

        # الضغط على زر التالي أو الضغط على مفتاح Enter
        next_btn = page.locator("#idSIButton9, input[type='submit'], button[type='submit']").first
        if next_btn.count() > 0 and next_btn.is_visible():
            next_btn.click()
        else:
            email_input.press("Enter")
        page.wait_for_timeout(2000)

        # 2. إدخال كلمة المرور (معرف مايكروسوفت الرسمي #i0118 أو حقل password)
        print("[OUTLOOK-DYNAMIC] Entering password...")
        pass_input = page.locator("#i0118, input[type='password'], input[name='passwd']").first
        pass_input.wait_for(state="visible", timeout=15000)
        pass_input.fill(email_password)
        take_snap(page, "outlook_02_password_entered")

        # الضغط على زر تسجيل الدخول أو مفتاح Enter
        sign_btn = page.locator("#idSIButton9, input[type='submit'], button[type='submit']").first
        if sign_btn.count() > 0 and sign_btn.is_visible():
            sign_btn.click()
        else:
            pass_input.press("Enter")
        page.wait_for_timeout(2500)

        # 3. تخطي أي شاشة وسيطة (Stay signed in / App promo)
        for _ in range(2):
            confirm_btn = page.locator("#idSIButton9, button:has-text('Yes'), button:has-text('No'), input[value='Yes'], input[value='No']").first
            if confirm_btn.count() > 0 and confirm_btn.is_visible():
                confirm_btn.click()
                page.wait_for_timeout(2000)

        take_snap(page, "outlook_03_logged_in")

        # 4. فتح صندوق الوارد مباشرة
        print("[OUTLOOK-DYNAMIC] Navigating directly to Outlook Inbox...")
        page.goto("https://outlook.live.com/mail/0/inbox", timeout=30000)
        page.wait_for_timeout(2500)
        take_snap(page, "outlook_04_inbox_opened")

        # 5. البحث الديناميكي عن رسالة Steam واستخراج الكود
        start_time = time.time()
        while time.time() - start_time < max_wait_seconds:
            page.wait_for_timeout(2000)

            # فحص فوري للنص بالكامل أو الضغط على رسالة Steam
            steam_item = page.locator("div[role='option']:has-text('Steam'), div:has-text('Steam Support'), span:has-text('Steam')").first
            if steam_item.count() > 0:
                print("[OUTLOOK-DYNAMIC] Steam email spotted! Opening message...")
                steam_item.click()
                page.wait_for_timeout(1500)
                take_snap(page, "outlook_05_message_opened")

            # قراءة محتوى الرسالة
            text = page.content()
            code = extract_code_from_text(text)
            if code:
                print(f"[OUTLOOK-DYNAMIC] [SUCCESS] Extracted Steam Code: [{code}]")
                page.close()
                return code

            print("[OUTLOOK-DYNAMIC] Waiting for Steam email...")

        take_snap(page, "outlook_error_timeout")
        page.close()
    except Exception as e:
        print(f"[OUTLOOK-DYNAMIC] Exception: {e}")
        take_snap(page, "outlook_exception")
        try:
            page.close()
        except Exception:
            pass

    return None
