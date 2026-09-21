import imaplib
import email
import re
import time

def extract_steam_code_from_outlook(email_user: str, email_pass: str, max_wait_sec: int = 60) -> str | None:
    print(f"[OUTLOOK] Checking inbox for {email_user} via IMAP...")
    imap_server = "outlook.office365.com"
    start_time = time.time()

    while time.time() - start_time < max_wait_sec:
        try:
            mail = imaplib.IMAP4_SSL(imap_server, 993)
            mail.login(email_user, email_pass)
            mail.select("INBOX")
            status, messages = mail.search(None, 'FROM "noreply@steampowered.com"')
            if status == "OK" and messages[0]:
                msg_ids = messages[0].split()
                latest_id = msg_ids[-1]
                status, msg_data = mail.fetch(latest_id, "(RFC822)")
                if status == "OK":
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() in ["text/plain", "text/html"]:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    body += payload.decode(errors="ignore")
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            body = payload.decode(errors="ignore")

                    match = re.search(r'\b([A-Z0-9]{5})\b', body)
                    if match:
                        code = match.group(1)
                        print(f"[OUTLOOK] [✓] Extracted Steam Code: {code}")
                        mail.logout()
                        return code
            mail.logout()
        except Exception as e:
            print(f"[OUTLOOK] Polling attempt error: {e}")
        time.sleep(3)

    print("[OUTLOOK] Timeout waiting for Steam verification email.")
    return None
