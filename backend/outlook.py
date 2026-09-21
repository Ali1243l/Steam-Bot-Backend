import imaplib
import email
from email.header import decode_header
import re
import time

def get_outlook_verification_code(email_address: str, email_password: str, max_attempts: int = 15) -> str:
    print(f"[OUTLOOK] Checking inbox for: {email_address} via IMAP...")
    for attempt in range(max_attempts):
        try:
            mail = imaplib.IMAP4_SSL("outlook.office365.com", 993)
            mail.login(email_address, email_password)
            mail.select("INBOX")

            status, messages = mail.search(None, '(FROM "Steam Support" SUBJECT "Steam" UNSEEN)')
            if not messages[0]:
                status, messages = mail.search(None, '(FROM "Steam" UNSEEN)')
            if not messages[0]:
                status, messages = mail.search(None, 'ALL')

            if messages[0]:
                mail_ids = messages[0].split()
                latest_id = mail_ids[-1]
                status, msg_data = mail.fetch(latest_id, "(RFC822)")

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

                        # بحث عن كود ستيم المكون من 5 أحرف أو أرقام
                        matches = re.findall(r'\b[A-Z0-9]{5}\b', body)
                        if matches:
                            mail.logout()
                            print(f"[OUTLOOK] Code found: {matches[0]}")
                            return matches[0]

            mail.logout()
        except Exception as e:
            print(f"[OUTLOOK] Attempt {attempt+1} notice: {e}")

        time.sleep(1.5)

    print("[OUTLOOK] Timeout waiting for verification code.")
    return None

# دالة مساعدة بنفس الاسم للتوافق التام
def get_latest_steam_code(email_address: str, email_password: str):
    return get_outlook_verification_code(email_address, email_password)
