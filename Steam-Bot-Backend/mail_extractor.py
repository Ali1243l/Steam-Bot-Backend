import re
import imaplib
import email
from email.header import decode_header
import logging
from playwright.async_api import BrowserContext

logger = logging.getLogger("orchestrator.mail")

async def fetch_code_from_outlook_imap(email_address: str, password: str, timeout_seconds: int = 30) -> str:
    """سحب كود ستيم من أوتلوك عبر بروتوكول IMAP فائق السرعة وبدون متصفح"""
    import asyncio
    logger.info(f"[OUTLOOK:IMAP] Connecting to outlook.office365.com for {email_address}...")
    
    for _ in range(timeout_seconds // 3):
        try:
            mail = imaplib.IMAP4_SSL("outlook.office365.com", 993)
            mail.login(email_address, password)
            mail.select("inbox")

            status, messages = mail.search(None, '(FROM "Steam Support")')
            if status == "OK" and messages[0]:
                msg_ids = messages[0].split()
                latest_id = msg_ids[-1]
                res, msg_data = mail.fetch(latest_id, "(RFC822)")
                
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() in ["text/plain", "text/html"]:
                                    body += part.get_payload(decode=True).decode(errors="ignore")
                        else:
                            body = msg.get_payload(decode=True).decode(errors="ignore")

                        pattern = r"(?:credentials:|code:?)\s*([A-Z0-9]{5})\b"
                        match = re.search(pattern, body, re.IGNORECASE)
                        if match:
                            mail.logout()
                            logger.info(f"[OUTLOOK:SUCCESS] Found Steam code via IMAP: {match.group(1).upper()}")
                            return match.group(1).upper()
            mail.logout()
        except Exception as e:
            logger.warning(f"[OUTLOOK:RETRY] Checking IMAP... ({e})")
        
        await asyncio.sleep(3)

    raise TimeoutError("Could not retrieve Steam code from Outlook inbox.")

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
    """الدالة الموحدة: تحدد نوع الإيميل تلقائياً"""
    domain = email.split("@")[-1].lower()
    if "outlook" in domain or "hotmail" in domain:
        return await fetch_code_from_outlook_imap(email, password, timeout_seconds)
    else:
        return await fetch_code_from_xomail(context, email, password, timeout_seconds)
