import re
import logging
from playwright.async_api import BrowserContext, Page

logger = logging.getLogger("orchestrator.mail")

class MailWorker:
    def __init__(self, context: BrowserContext, email: str, password: str):
        self.context = context
        self.email = email
        self.password = password
        self.page: Page = None
        self.is_outlook = any(d in email.lower() for d in ["outlook", "hotmail", "live.com"])

    async def pre_login(self):
        """تسجيل الدخول المبكر بالتوازي مع خطوات ستيم"""
        self.page = await self.context.new_page()
        try:
            if self.is_outlook:
                logger.info(f"[MAIL:PARALLEL] Pre-logging into Outlook for {self.email}...")
                await self.page.goto("https://login.live.com/", wait_until="domcontentloaded", timeout=30000)

                # إدخال البريد
                email_input = await self.page.wait_for_selector("input[type='email'], input[name='loginfmt']", timeout=15000)
                await email_input.fill(self.email)
                await self.page.keyboard.press("Enter")
                await self.page.wait_for_timeout(2000)

                # إدخال كلمة المرور
                pwd_input = await self.page.wait_for_selector("input[type='password'], input[name='passwd']", timeout=15000)
                await pwd_input.fill(self.password)
                await self.page.keyboard.press("Enter")
                await self.page.wait_for_timeout(2500)

                # تخطي شاشة البقاء مسجلاً (Stay signed in)
                decline_btn = await self.page.query_selector("input#declineButton, input#idSIButton9, button:has-text('No')")
                if decline_btn:
                    try:
                        await decline_btn.click(force=True)
                    except Exception:
                        pass

                # التوجه المباشر لصندوق الوارد
                await self.page.goto("https://outlook.live.com/mail/0/inbox", wait_until="domcontentloaded", timeout=35000)
                logger.info("[MAIL:PARALLEL] Outlook Inbox is primed and ready!")
            else:
                logger.info(f"[MAIL:PARALLEL] Pre-logging into xomail for {self.email}...")
                await self.page.goto("http://xomail.club/", wait_until="domcontentloaded", timeout=25000)
                await self.page.wait_for_selector("#rcmloginuser", timeout=10000)
                await self.page.fill("#rcmloginuser", self.email)
                await self.page.fill("#rcmloginpwd", self.password)
                await self.page.keyboard.press("Enter")
                await self.page.wait_for_selector("table#messagelist", timeout=15000)
                logger.info("[MAIL:PARALLEL] xomail Inbox is primed and ready!")
        except Exception as e:
            logger.warning(f"[MAIL:PRE_LOGIN_WARN] Pre-login encountered an issue (will retry during fetch): {str(e)}")

    async def fetch_code(self, timeout_seconds: int = 40) -> str:
        """جلب الكود فوراً وبأعلى سرعة لأن الجلسة مفتوحة مسبقاً"""
        if not self.page or self.page.is_closed():
            await self.pre_login()

        logger.info(f"[MAIL:FETCH] Monitoring incoming Steam verification email for {self.email}...")

        if self.is_outlook:
            steam_msg_selector = "div[role='option']:has-text('Steam'), div[aria-label*='Steam'], div:has-text('Steam Support')"
            for _ in range(timeout_seconds // 2):
                try:
                    msg = await self.page.query_selector(steam_msg_selector)
                    if msg:
                        await msg.click(force=True)
                        break
                except Exception:
                    pass
                await self.page.wait_for_timeout(2000)

            await self.page.wait_for_timeout(2000)
            body_text = await self.page.inner_text("body")

            pattern = r"(?:credentials:|code:?)\s*([A-Z0-9]{5})\b"
            match = re.search(pattern, body_text, re.IGNORECASE)
            if match:
                return match.group(1).upper()

            fallback = re.search(r"\b([A-Z0-9]{5})\b", body_text)
            if fallback:
                return fallback.group(1).upper()

        else:
            for _ in range(timeout_seconds // 2):
                first_row = await self.page.query_selector("table#messagelist tbody tr.message:first-child")
                if first_row:
                    row_text = await first_row.inner_text()
                    if "Steam" in row_text:
                        await first_row.dblclick(force=True)
                        break

                refresh_btn = await self.page.query_selector("a.button-checkmail, a.toolbar-button.refresh, #rcmbtn106")
                if refresh_btn:
                    await refresh_btn.click(force=True)
                await self.page.wait_for_timeout(2000)

            await self.page.wait_for_timeout(2000)
            content_frame = None
            for frame in self.page.frames:
                if "messagecontframe" in frame.name or "watermark" in frame.name:
                    content_frame = frame
                    break
            target = content_frame if content_frame else self.page

            code_el = await target.query_selector("td.v1title-48, td[class*='title-48'], td[style*='font-size: 48px']")
            if code_el:
                code_text = (await code_el.inner_text()).strip()
                if code_text and len(code_text) <= 8:
                    return code_text

            body_text = await target.inner_text("body")
            match = re.search(r"(?:credentials:|code:?)\s*([A-Z0-9]{5})\b", body_text, re.IGNORECASE)
            if match:
                return match.group(1).upper()

            fallback = re.search(r"\b([A-Z0-9]{5})\b", body_text)
            if fallback:
                return fallback.group(1).upper()

        raise TimeoutError("Could not extract verification code from email.")

    async def close(self):
        if self.page and not self.page.is_closed():
            await self.page.close()
