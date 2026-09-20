async def fetch_code(self, timeout_seconds: int = 45) -> str:
        if not self.page or self.page.is_closed():
            await self.pre_login()

        logger.info(f"[MAIL:FETCH] Fast monitoring for Steam code: {self.email}...")

        if self.is_outlook:
            # محددات مباشرة وقوية وسريعة لرسائل ستيم
            steam_click_selectors = [
                "div[aria-label*='Steam Support']",
                "div[aria-label*='Steam']",
                "div[role='option']:has-text('Steam')",
                "span:has-text('Steam Support')"
            ]

            code_found = None
            for attempt in range(timeout_seconds):
                # فحص فوري وسريع للرسالة الحالية
                for sel in steam_click_selectors:
                    try:
                        msg = await self.page.query_selector(sel)
                        if msg:
                            await msg.click(force=True)
                            logger.info("[OUTLOOK:CLICK] Clicked Steam email instantly!")
                            break
                    except Exception:
                        pass

                # قراءة محتوى الصفحة مباشرة
                body_text = await self.page.inner_text("body")
                match = re.search(r"(?:credentials:|code:?)\s*([A-Z0-9]{5})\b", body_text, re.IGNORECASE)
                if match:
                    code_found = match.group(1).upper()
                    logger.info(f"[OUTLOOK:FAST_SUCCESS] Captured Steam Code: {code_found}")
                    return code_found

                fallback = re.search(r"\b([A-Z0-9]{5})\b", body_text)
                if fallback and "STEAM" in body_text.upper():
                    code_found = fallback.group(1).upper()
                    logger.info(f"[OUTLOOK:FAST_SUCCESS] Fallback captured Code: {code_found}")
                    return code_found

                # ضغط زر التحديث أو F5 كل ثانيتين لإجبار Outlook على جلب الرسالة الجديدة
                if attempt % 2 == 0 and attempt > 0:
                    try:
                        refresh_btn = await self.page.query_selector("button[aria-label*='Refresh'], button[id*='refresh']")
                        if refresh_btn:
                            await refresh_btn.click(force=True)
                        else:
                            await self.page.keyboard.press("F5")
                    except Exception:
                        pass

                await asyncio.sleep(1)

            if not code_found:
                raise TimeoutError("Could not capture Outlook verification code in time.")

        else:
            # مسار xomail السريع
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
                await asyncio.sleep(1.5)

            await asyncio.sleep(1)
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
