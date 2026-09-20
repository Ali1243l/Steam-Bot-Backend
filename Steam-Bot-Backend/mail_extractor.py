import re
import logging
from playwright.async_api import BrowserContext

logger = logging.getLogger("orchestrator.mail")

async def fetch_code_from_outlook_web(context: BrowserContext, email: str, password: str, timeout_seconds: int = 50) -> str:
    mail_page = await context.new_page()
    try:
        logger.info(f"[OUTLOOK:WEB] Logging into Outlook Web for {email}...")
        await mail_page.goto("https://login.live.com/", wait_until="domcontentloaded", timeout=30000)

        # 1. إدخال الإيميل
        email_input = await mail_page.wait_for_selector("input[type='email'], input[name='loginfmt']", timeout=15000)
        await email_input.fill(email)
        await mail_page.keyboard.press("Enter")
        await mail_page.wait_for_timeout(2500)

        # 2. إدخال كلمة المرور
        pwd_input = await mail_page.wait_for_selector("input[type='password'], input[name='passwd']", timeout=15000)
        await pwd_input.fill(password)
        await mail_page.keyboard.press("Enter")

        # انتظار انتهاء التحويلات التلقائية لمايكروسوفت
        await mail_page.wait_for_load_state("networkidle", timeout=15000)
        await mail_page.wait_for_timeout(3000)

        # 3. تخطي نافذة "Stay signed in?" إن ظهرت
        decline_btn = await mail_page.query_selector("input#declineButton, input#idSIButton9, button:has-text('No'), button:has-text('Yes')")
        if decline_btn:
            try:
                await decline_btn.click(force=True)
                await mail_page.wait_for_timeout(2000)
            except Exception:
                pass

        # 4. التوجه المباشر لصندوق البريد والتأكد من استقراره
        logger.info("[OUTLOOK:WEB] Navigating directly to inbox...")
        await mail_page.goto("https://outlook.live.com/mail/0/inbox", wait_until="domcontentloaded", timeout=40000)
        await mail_page.wait_for_load_state("networkidle", timeout=15000)
        await mail_page.wait_for_timeout(4000)

        # 5. البحث عن رسالة Steam والضغط عليها
        steam_row_selector = "div[role='option']:has-text('Steam'), div[aria-label*='Steam'], div:has-text('Steam Support')"
        msg_found = False
        for _ in range(timeout_seconds // 4):
            try:
                msg = await mail_page.query_selector(steam_row_selector)
                if msg:
                    await msg.click(force=True)
                    msg_found = True
                    break
            except Exception:
                pass
            await mail_page.wait_for_timeout(3500)

        await mail_page.wait_for_timeout(3000)

        # 6. استخراج الكود بدقة (الحروف والأرقام مثل 3KQ6T)
        body_text = await mail_page.inner_text("body")
        
        # استخراج من الكود الكبير أو النمط القياسي
        pattern = r"(?:credentials:|code:?)\s*([A-Z0-9]{5})\b"
        match = re.search(pattern, body_text, re.IGNORECASE)
        if match:
            code = match.group(1).upper()
            logger.info(f"[OUTLOOK:SUCCESS] Found Steam code: {code}")
            return code

        # استخراج بديل لأي 5 أحرف وأرقام تظهر بعد اسم المستخدم
        fallback_match = re.search(r"\b([A-Z0-9]{5})\b", body_text)
        if fallback_match:
            code = fallback_match.group(1).upper()
            logger.info(f"[OUTLOOK:SUCCESS] Found Fallback Steam code: {code}")
            return code

        raise ValueError("Could not locate verification code inside Outlook email body.")
    finally:
        await mail_page.close()

async def fetch_code_from_xomail(context: BrowserContext, email: str, password: str, timeout_seconds: int = 40) -> str:
    mail_page = await context.new_page()
    try:
        logger.info(f"[MAIL] Logging into xomail for {email}...")
        await mail_page.goto("http://xomail.club/", wait_until="domcontentloaded", timeout=25000)

        await mail_page.wait_for_selector("#rcmloginuser", timeout=10000)
        await mail_page.fill("#rcmloginuser", email)
        await mail_page.fill("#rcmloginpwd", password)
        await mail_page.keyboard.press("Enter")

        await mail_page.wait_for_selector("table#messagelist", timeout=15000)

        for _ in range(timeout_seconds // 3):
            first_row = await mail_page.query_selector("table#messagelist tbody tr.message:first-child")
            if first_row:
                row_text = await first_row.inner_text()
                if "Steam" in row_text:
                    await first_row.dblclick(force=True)
                    break

            refresh_btn = await mail_page.query_selector("a.button-checkmail, a.toolbar-button.refresh, #rcmbtn106")
            if refresh_btn:
                await refresh_btn.click(force=True)
            await mail_page.wait_for_timeout(3000)

        await mail_page.wait_for_timeout(2000)

        content_frame = None
        for frame in mail_page.frames:
            if "messagecontframe" in frame.name or "watermark" in frame.name:
                content_frame = frame
                break
        target = content_frame if content_frame else mail_page

        code_el = await target.query_selector("td.v1title-48, td[class*='title-48'], td[style*='font-size: 48px']")
        if code_el:
            clean_code = (await code_el.inner_text()).strip()
            if clean_code and len(clean_code) <= 8:
                return clean_code

        body_text = await target.inner_text("body")
        match = re.search(r"(?:credentials:|code:?)\s*([A-Z0-9]{5})\b", body_text, re.IGNORECASE)
        if match:
            return match.group(1).upper()

        fallback = re.search(r"\b([A-Z0-9]{5})\b", body_text)
        if fallback:
            return fallback.group(1).upper()

        raise ValueError("Could not extract verification code from latest email.")
    finally:
        await mail_page.close()

async def fetch_steam_code(context: BrowserContext, email: str, password: str, timeout_seconds: int = 45) -> str:
    domain = email.split("@")[-1].lower()
    if "outlook" in domain or "hotmail" in domain or "live.com" in domain:
        return await fetch_code_from_outlook_web(context, email, password, timeout_seconds)
    else:
        return await fetch_code_from_xomail(context, email, password, timeout_seconds)
