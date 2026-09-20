import re
import logging
from playwright.async_api import BrowserContext

logger = logging.getLogger("orchestrator.mail")

async def fetch_code_from_outlook_web(context: BrowserContext, email: str, password: str, timeout_seconds: int = 45) -> str:
    """تسجيل الدخول لبريد أوتلوك عبر المتصفح وسحب كود ستيم"""
    mail_page = await context.new_page()
    try:
        logger.info(f"[OUTLOOK:WEB] Logging into Outlook Web for {email}...")
        await mail_page.goto("https://login.live.com/", wait_until="domcontentloaded", timeout=30000)

        # 1. إدخال الإيميل
        email_input = await mail_page.wait_for_selector("input[type='email'], input[name='loginfmt']", timeout=15000)
        await email_input.fill(email)
        await mail_page.keyboard.press("Enter")
        await mail_page.wait_for_timeout(2500)

        # 2. إدخال الباسوورد
        pwd_input = await mail_page.wait_for_selector("input[type='password'], input[name='passwd']", timeout=15000)
        await pwd_input.fill(password)
        await mail_page.keyboard.press("Enter")
        await mail_page.wait_for_timeout(3000)

        # 3. تخطي شاشة "Stay signed in?" في حال ظهورها
        decline_btn = await mail_page.query_selector("input#declineButton, input#idSIButton9, button:has-text('No'), button:has-text('Yes')")
        if decline_btn:
            try:
                await decline_btn.click(force=True)
            except Exception:
                pass

        # 4. التوجه لصندوق الوارد في أوتلوك
        logger.info("[OUTLOOK:WEB] Navigating to Outlook Inbox...")
        await mail_page.goto("https://outlook.live.com/mail/0/inbox", wait_until="domcontentloaded", timeout=35000)
        await mail_page.wait_for_timeout(5000)

        # البحث عن رسالة ستيم وفتحها
        steam_msg_selector = "div[role='option']:has-text('Steam'), div[aria-label*='Steam'], div:has-text('Steam Support')"
        for _ in range(timeout_seconds // 4):
            msg = await mail_page.query_selector(steam_msg_selector)
            if msg:
                await msg.click(force=True)
                break
            await mail_page.wait_for_timeout(4000)

        await mail_page.wait_for_timeout(3000)

        # 5. استخراج الكود من محتوى الرسالة
        body_text = await mail_page.inner_text("body")
        pattern = r"(?:credentials:|code:?)\s*([A-Z0-9]{5})\b"
        match = re.search(pattern, body_text, re.IGNORECASE)
        if match:
            code = match.group(1).upper()
            logger.info(f"[OUTLOOK:SUCCESS] Found Steam code: {code}")
            return code

        fallback_match = re.search(r"\b([A-Z0-9]{5})\b", body_text)
        if fallback_match:
            code = fallback_match.group(1).upper()
            logger.info(f"[OUTLOOK:SUCCESS] Found Fallback Steam code: {code}")
            return code

        raise ValueError("Could not find verification code inside Outlook email.")
    finally:
        await mail_page.close()

async def fetch_code_from_xomail(context: BrowserContext, email: str, password: str, timeout_seconds: int = 40) -> str:
    """استخراج الكود من بريد xomail / roundcube"""
    mail_page = await context.new_page()
    try:
        logger.info(f"[MAIL] Logging into xomail for {email}...")
        await mail_page.goto("http://xomail.club/", wait_until="domcontentloaded", timeout=25000)

        await mail_page.wait_for_selector("#rcmloginuser", timeout=10000)
        await mail_page.fill("#rcmloginuser", email)
        await mail_page.fill("#rcmloginpwd", password)
        await mail_page.keyboard.press("Enter")

        await mail_page.wait_for_selector("table#messagelist", timeout=15000)

        logger.info("[MAIL] Looking for the latest Steam email...")
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
        pattern = r"(?:credentials:|code:?)\s*([A-Z0-9]{5})\b"
        match = re.search(pattern, body_text, re.IGNORECASE)
        if match:
            return match.group(1).upper()

        fallback_match = re.search(r"\b([A-Z0-9]{5})\b", body_text)
        if fallback_match:
            return fallback_match.group(1).upper()

        raise ValueError("Could not extract verification code from latest email.")
    finally:
        await mail_page.close()

async def fetch_steam_code(context: BrowserContext, email: str, password: str, timeout_seconds: int = 40) -> str:
    """الموجّه الذكي: يفحص النطاق ويشغّل الطريقة المناسبة"""
    domain = email.split("@")[-1].lower()
    if "outlook" in domain or "hotmail" in domain or "live.com" in domain:
        return await fetch_code_from_outlook_web(context, email, password, timeout_seconds)
    else:
        return await fetch_code_from_xomail(context, email, password, timeout_seconds)
