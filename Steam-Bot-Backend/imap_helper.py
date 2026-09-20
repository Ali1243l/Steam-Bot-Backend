"""
imap_helper.py - Generic IMAP Email Utility
Connects to an IMAP server over SSL, retrieves the latest email from a sender,
and parses verification patterns from the message content.
"""

import imaplib
import email
from email.header import decode_header
import re
import logging
from typing import Optional

logger = logging.getLogger("imap_helper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _decode_mime_words(raw_header: str) -> str:
    """Helper to decode MIME-encoded email headers."""
    decoded_fragments = decode_header(raw_header)
    header_parts = []
    for text, encoding in decoded_fragments:
        if isinstance(text, bytes):
            try:
                header_parts.append(text.decode(encoding or "utf-8", errors="replace"))
            except LookupError:
                header_parts.append(text.decode("utf-8", errors="replace"))
        else:
            header_parts.append(str(text))
    return "".join(header_parts)


def _extract_plain_text(message: email.message.Message) -> str:
    """Recursively extracts plain text content from an email message structure."""
    body_parts = []

    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # Avoid reading attachments
            if "attachment" in content_disposition:
                continue

            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        body_parts.append(payload.decode(charset, errors="replace"))
                    except LookupError:
                        body_parts.append(payload.decode("utf-8", errors="replace"))
    else:
        payload = message.get_payload(decode=True)
        if payload:
            charset = message.get_content_charset() or "utf-8"
            try:
                body_parts.append(payload.decode(charset, errors="replace"))
            except LookupError:
                body_parts.append(payload.decode("utf-8", errors="replace"))

    return "\n".join(body_parts)


def fetch_verification_code(
    email_address: str,
    password: str,
    imap_server: str,
    sender_filter: Optional[str] = None,
    port: int = 993,
    timeout_seconds: int = 30,
) -> Optional[str]:
    """
    Connects to the specified IMAP server over SSL, searches the INBOX for
    the latest message (optionally filtered by sender), and extracts a 5-character
    alphanumeric verification code.

    Args:
        email_address: Full username/email for IMAP authentication.
        password: Password for the email account.
        imap_server: Hostname of the IMAP server (e.g., 'imap.example.com').
        sender_filter: Optional sender address to filter incoming mail (e.g., 'noreply@steampowered.com').
        port: SSL port for IMAP (defaults to 993).
        timeout_seconds: Network timeout in seconds.

    Returns:
        The extracted 5-character alphanumeric string if found, otherwise None.
    """
    mail: Optional[imaplib.IMAP4_SSL] = None

    try:
        logger.info(f"[IMAP:CONNECT] Connecting to {imap_server}:{port} as {email_address}...")
        mail = imaplib.IMAP4_SSL(imap_server, port=port, timeout=timeout_seconds)

        logger.info("[IMAP:LOGIN] Authenticating credentials...")
        mail.login(email_address, password)

        logger.info("[IMAP:SELECT] Selecting mailbox INBOX (readonly mode)...")
        status, _ = mail.select("INBOX", readonly=True)
        if status != "OK":
            logger.error(f"[IMAP:SELECT_FAILED] Could not open INBOX. Status: {status}")
            return None

        # Build search criteria
        if sender_filter:
            search_query = f'(FROM "{sender_filter}")'
        else:
            search_query = "ALL"

        logger.info(f"[IMAP:SEARCH] Executing query: {search_query}")
        status, data = mail.search(None, search_query)

        if status != "OK" or not data or not data[0]:
            logger.warning("[IMAP:NO_MESSAGES] No messages found matching search criteria.")
            return None

        # Message IDs are space-separated strings; the last ID is the newest
        message_ids = data[0].split()
        latest_id = message_ids[-1]
        logger.info(f"[IMAP:FETCH] Retrieving newest message ID: {latest_id.decode('ascii', errors='ignore')}")

        status, msg_data = mail.fetch(latest_id, "(RFC822)")
        if status != "OK" or not msg_data:
            logger.error(f"[IMAP:FETCH_FAILED] Could not retrieve message content for ID {latest_id}")
            return None

        # Parse raw RFC822 email payload
        raw_email = msg_data[0][1]
        parsed_message = email.message_from_bytes(raw_email)

        subject = _decode_mime_words(parsed_message.get("Subject", "(No Subject)"))
        sender = _decode_mime_words(parsed_message.get("From", "(Unknown Sender)"))
        logger.info(f"[IMAP:MSG_INFO] From: {sender} | Subject: {subject}")

        # Extract text body
        body = _extract_plain_text(parsed_message)
        if not body:
            logger.warning("[IMAP:EMPTY_BODY] Message body contains no readable plain text.")
            return None

        # Regex matching a 5-character uppercase alphanumeric code bound by word boundaries
        # Excludes standard English filler words by checking alphanumeric combinations
        code_pattern = re.compile(r"\b([A-Z0-9]{5})\b")
        matches = code_pattern.findall(body)

        if not matches:
            logger.warning("[IMAP:CODE_NOT_FOUND] No 5-character alphanumeric token found in message body.")
            return None

        # Returns the first matching token found
        extracted_code = matches[0]
        logger.info(f"[IMAP:CODE_EXTRACTED] Successfully parsed verification code: {extracted_code}")
        return extracted_code

    except imaplib.IMAP4.error as err:
        logger.error(f"[IMAP:AUTH_ERROR] IMAP protocol or authentication failure: {err}")
        return None
    except TimeoutError:
        logger.error(f"[IMAP:TIMEOUT] Connection to {imap_server} timed out after {timeout_seconds}s.")
        return None
    except Exception as exc:
        logger.exception(f"[IMAP:UNEXPECTED_ERROR] Error processing email: {exc}")
        return None

    finally:
        if mail:
            try:
                mail.close()
            except Exception:
                pass
            try:
                mail.logout()
            except Exception:
                pass
            logger.info("[IMAP:DISCONNECT] Connection closed.")
