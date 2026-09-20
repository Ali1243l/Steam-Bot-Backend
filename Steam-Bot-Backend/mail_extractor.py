import re
import logging
from playwright.async_api import BrowserContext

logger = logging.getLogger("orchestrator.mail")

async def fetch_code_from_xomail(
    context: BrowserContext,
    email: str,
    password: str,
    timeout_seconds: int = 60
) -> str:
    mail_page = await context.new_page()
    try:
        logger.info(f"[MAIL] Logging into Roundcube Webmail for {email}...")
        await mail_page.goto("http://xomail.club/", wait_until="domcontentloaded", timeout=30000)

        # تسجيل الدخول لبريد xomail
        await mail_page.wait_for_selector("#rcmloginuser", timeout=15000)
        await mail_page.fill("#rcmloginuser", email)
        await mail_page.fill("#rcmloginpwd", password)
        await mail_page.click("#rcmloginsubmit")
        await mail_page.wait_for_timeout(4000)

        # البحث عن رسالة Steam Support تحديداً
        logger.info("[MAIL] Searching for Steam Account Verification email...")
        steam_row_selector = "tr.message:has-text('Steam Support'), tr.message:has-text('Steam Account Verification'), tr.message:has-text('Steam')"
        
        # محاولة تحديث البريد إذا لم تظهر الرسالة فوراً
        message_found = False
        for attempt in range(timeout_seconds // 5):
            row = await mail_page.query_selector(steam_row_selector)
            if row:
                message_found = True
                await row.dblclick(force=True)
                break
            
            # الضغط على زر Refresh لتحديث الصندوق
            refresh_btn = await mail_page.query_selector("a.button-checkmail, a.toolbar-button.refresh, #rcmbtn106")
            if refresh_btn:
                await refresh_btn.click(force=True)
            await mail_page.wait_for_timeout(5000)

        if not message_found:
            # فتح أول رسالة موجودة بالصندوق كخيار بديل
            first_msg = await mail_page.wait_for_selector("table#messagelist tr.message, tr.message", timeout=10000)
            if first_msg:
                await first_msg.dblclick(force=True)

        await mail_page.wait_for_timeout(4000)

        # التعامل مع الـ iframe إذا كانت محتويات الرسالة بداخله
        content_frame = None
        for frame in mail_page.frames:
            if "messagecontframe" in frame.name or "watermark" in frame.name:
                content_frame = frame
                break
        
        target = content_frame if content_frame else mail_page

        # 1. الاستخراج المباشر باستخدام كلاس كود ستيم الدقيق
        code_el = await target.query_selector("td.v1title-48, td[class*='title-48'], td[style*='font-size: 48px']")
        if code_el:
            raw_text = await code_el.inner_text()
            clean_code = raw_text.strip()
            if clean_code and len(clean_code) <= 8:
                logger.info(f"[MAIL:SUCCESS] Extracted Steam Code directly via selector: {clean_code}")
                return clean_code

        # 2. الاستخراج الاحتياطي عبر Regex يدعم الحروف الكبيرة والأرقام (مثل DDQVT)
        body_text = await target.inner_text("body")
        # البحث عن كود مكون من 5 خانات (حروف كبيرة وأرقام) بعد عبارة credentials أو code
        pattern = r"(?:credentials:|code:?)\s*([A-Z0-9]{5})\b"
        match = re.search(pattern, body_text, re.IGNORECASE)
        if match:
            extracted = match.group(1).upper()
            logger.info(f"[MAIL:SUCCESS] Extracted Steam Code via Regex: {extracted}")
            return extracted

        # خيار أخير: التقاط أي كلمة من 5 أحرف كابيتال في جسم الرسالة
        fallback_match = re.search(r"\b([A-Z0-9]{5})\b", body_text)
        if fallback_match:
            extracted = fallback_match.group(1).upper()
            logger.info(f"[MAIL:SUCCESS] Extracted Fallback 5-char Code: {extracted}")
            return extracted

        raise ValueError("Could not find the Steam verification code inside the email body.")

    finally:
        await mail_page.close()
