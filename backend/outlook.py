import re
import time

def extract_code_from_text(text: str) -> str:
    # الكود في ستيم دائماً 5 أحرف أو أرقام كبيرة
    matches = re.findall(r'\b[A-Z0-9]{5}\b', text)
    blacklist = {"STEAM", "VALVE", "HTTPS", "LOGIN", "INBOX", "ENTER", "CLICK", "RESET", "HELP1", "ERROR"}
    for m in matches:
        if m not in blacklist and not m.isdigit(): # كود ستيم عادة يحتوي على أحرف وأرقام معاً
            return m
    for m in matches:
        if m not in blacklist:
            return m
    return None

def get_outlook_verification_code(email_address: str, email_password: str, browser_context, max_wait_seconds: int = 40) -> str:
    print(f"[OUTLOOK-HEADLESS] Opening Outlook Web for {email_address}...")
    page = browser_context.new_page()
    try:
        page.goto("https://login.live.com/", timeout=30000)
        page.wait_for_timeout(1000)

        # 1. إدخال الإيميل
        email_field = page.locator("input[type='email'], input[name='loginfmt']")
        email_field.fill(email_address)
        page.locator("button:has-text('Next'), input[type='submit'][value='Next']").click()
        page.wait_for_timeout(1500)

        # 2. إدخال الباسورد
        pass_field = page.locator("input[type='password'], input[name='passwd']")
        pass_field.fill(email_password)
        page.locator("button:has-text('Sign in'), input[type='submit'][value='Sign in']").click()
        page.wait_for_timeout(2000)

        # 3. تخطي رسالة البقاء مسجلاً (Stay signed in?)
        stay_btn = page.locator("button:has-text('Yes'), button:has-text('No'), input[value='Yes'], input[value='No']").first
        if stay_btn.count() > 0:
            stay_btn.click()
            page.wait_for_timeout(2000)

        # 4. الذهاب المباشر إلى صندوق الوارد Outlook Web
        print("[OUTLOOK-HEADLESS] Navigating to inbox...")
        page.goto("https://outlook.live.com/mail/0/inbox", timeout=30000)
        
        start_time = time.time()
        while time.time() - start_time < max_wait_seconds:
            page.wait_for_timeout(2000)
            
            # البحث عن رسالة ستيم
            steam_msg = page.locator("div[role='option']:has-text('Steam'), div:has-text('Steam Support'), span:has-text('Steam')").first
            if steam_msg.count() > 0:
                print("[OUTLOOK-HEADLESS] Steam email found! Clicking to read...")
                steam_msg.click()
                page.wait_for_timeout(1500)

                # قراءة نص الرسالة واستخراج الكود
                content = page.content()
                code = extract_code_from_text(content)
                if code:
                    print(f"[OUTLOOK-HEADLESS] Successfully retrieved Steam code: [{code}]")
                    page.close()
                    return code

            print("[OUTLOOK-HEADLESS] Waiting for Steam email to appear...")

        page.close()
    except Exception as e:
        print(f"[OUTLOOK-HEADLESS] Error: {e}")
        try:
            page.close()
        except Exception:
            pass
            
    return None
