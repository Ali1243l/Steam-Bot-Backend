import re
import logging
import asyncio
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
        """تسجيل الدخول المبكر لـ Outlook أو Xomail"""
        self.page = await self.context.new_page()
        try:
            if self.is_outlook:
                logger.info(f"[OUTLOOK:PARALLEL] Navigating to direct login for {self.email}...")
                # استخدام الرابط المباشر لتسجيل الدخول الفوري دون صفحات هبوط
                await self.page.goto("https://outlook.live.com/owa/?nlp=1", wait_until="domcontentloaded", timeout=35000)

                # 1. إدخال الإيميل
                email_selector = "input#i0116, input[name='loginfmt'], input[type='email'], input[type='text']:visible"
                email_input = await self.page.wait_for_selector(email_selector, timeout=20000)
                await email_input.click(force=True)
                await email_input.fill("")
                await email_input.fill(self.email)
                await self.page.keyboard.press("Enter")
                
                # زر التالي إن لم يستجب Enter
                next_btn = await self.page.query_selector("input#idSIButton9, button[type='submit']")
                if next_btn:
                    try:
                        await next_btn.click(force=True)
                    except Exception:
                        pass

                await asyncio.sleep(2.5)

                # 2. إدخال كلمة المرور
                pwd_selector = "input#i0118, input[name='passwd'], input[type='password']:visible"
                pwd_input = await self.page.wait_for_selector(pwd_selector, timeout=20000)
                await pwd_input.click(force=True)
                await pwd_input.fill("")
                await pwd_input.fill(self.password)
                await self.page.keyboard.press("Enter")

                submit_pwd_btn = await self.page.query_selector("input#idSIButton9, button[type='submit']")
                if submit_pwd_btn:
                    try:
                        await submit_pwd_btn.click(force=True)
                    except Exception:
                        pass

                await asyncio.sleep(3)

                # 3. تخطي شاشة "Stay signed in?"
                decline_btn = await self.page.query_selector("input#declineButton, input#idBtn_Back, button:has-text('No'), input[value='No']")
                if decline_btn:
                    try:
                        await decline_btn.click(force=True)
                        await asyncio.sleep(2)
                    except Exception:
                        pass

                logger.info("[OUTLOOK:PARALLEL] Navigating to mailbox...")
                await self.page.goto("https://outlook.live.com/mail/0/inbox", wait_until="domcontentloaded", timeout=40000)
                logger.info("[OUTLOOK:PARALLEL] Outlook inbox ready and standing by.")
            else:
                logger.info(f"[MAIL:PARALLEL] Opening xomail for {self.email}...")
                await self.page.goto("http://xomail.club/", wait_until="domcontentloaded", timeout=25000)
                await self.page.wait_for_selector("#rcmloginuser", timeout=10000)
                await self.page.fill("#rcmloginuser", self.email)
                await self.page.fill("#rcmloginpwd", self.password)
                await self.page.keyboard.press("Enter")
                await self.page.wait_for_selector("table#messagelist", timeout=15000)
                logger.info("[MAIL:PARALLEL] xomail inbox ready.")
        except Exception as e:
            logger.warning(f"[MAIL:PRE_LOGIN_WARN] Pre-login issue: {str(e)}")

    async def fetch_code(self, timeout_seconds: int = 50) -> str:
        """استخراج كود ستيم من البريد"""
        if not self.page or self.page.is_closed():
            await self.pre_login()

        logger.info(f"[MAIL:FETCH] Monitoring incoming Steam verification email for {self.email}...")

        if self.is_outlook:
            # البحث عن رسالة ستيم في Outlook
            steam_msg_selector = "xpath=//div[@role='option'][contains(., 'Steam')] | xpath=//div[@aria-label and contains(@aria-label, 'Steam')] | div:has-text('Steam Support')"
            msg_clicked = False

            for _ in range(timeout_seconds // 3):
                try:
                    msg = await self.page.query_selector(steam_msg_selector)
                    if msg:
                        await msg.click(force=True)
                        msg_clicked = True
                        break
                except Exception:
                    pass
                await asyncio.sleep(3)

            await asyncio.sleep(2)
            body_text = await self.page.inner_text("body")

            match = re.search(r"(?:credentials:|code:?)\s*([A-Z0-9]{5})\b", body_text, re.IGNORECASE)
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
                await asyncio.sleep(2)

            await asyncio.sleep(2)
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
