import re
import logging
from playwright.async_api import BrowserContext

logger = logging.getLogger("orchestrator.mail")

async def fetch_code_from_xomail(
    context: BrowserContext,
    email: str,
    password: str,
    timeout_seconds: int = 40
) -> str:
    mail_page = await context.new_page()
    try:
        logger.info(f"[MAIL] Logging into xomail for {email}...")
        await mail_page.goto("http://xomail.club/", wait_until="domcontentloaded", timeout=25000)

        await mail_page.wait_for_selector("#rcmloginuser", timeout=10000)
        await mail_page.fill("#rcmloginuser", email)
        await mail_page.fill("#rcmloginpwd", password)
        await mail_page.keyboard.press("Enter")

        # انتظار جدول الرسائل
        await mail_page.wait_for_selector("table#messagelist", timeout=15000)

        # استهداف أول رسالة فقط (وهي دائماً الأحدث زمنيّاً) والتأكد أنها من Steam
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

        # قراءة محتوى الرسالة
        content_frame = None
        for frame in mail_page.frames:
            if "messagecontframe" in frame.name or "watermark" in frame.name:
                content_frame = frame
                break
        target = content_frame if content_frame else mail_page

        # 1. المحدد المباشر الدقيق لكود ستيم
        code_el = await target.query_selector("td.v1title-48, td[class*='title-48'], td[style*='font-size: 48px']")
        if code_el:
            clean_code = (await code_el.inner_text()).strip()
            if clean_code and len(clean_code) <= 8:
                logger.info(f"[MAIL:SUCCESS] Extracted latest Steam code: {clean_code}")
                return clean_code

        # 2. استخراج عبر Regex للحروف الكبيرة والأرقام
        body_text = await target.inner_text("body")
        pattern = r"(?:credentials:|code:?)\s*([A-Z0-9]{5})\b"
        match = re.search(pattern, body_text, re.IGNORECASE)
        if match:
            extracted = match.group(1).upper()
            logger.info(f"[MAIL:SUCCESS] Regex extracted code: {extracted}")
            return extracted

        fallback_match = re.search(r"\b([A-Z0-9]{5})\b", body_text)
        if fallback_match:
            extracted = fallback_match.group(1).upper()
            logger.info(f"[MAIL:SUCCESS] Fallback extracted code: {extracted}")
            return extracted

        raise ValueError("Could not extract verification code from latest email.")

    finally:
        await mail_page.close()
