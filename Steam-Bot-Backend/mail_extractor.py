async def fetch_code(self, timeout_seconds: int = 50) -> str:
        if not self.page or self.page.is_closed():
            await self.pre_login()

        logger.info(f"[MAIL:FETCH] Monitoring incoming Steam verification email for {self.email}...")

        if self.is_outlook:
            # محددات مرنة وشاملة جداً لرسائل ستيم داخل Outlook Web
            steam_msg_selector = (
                "div:has-text('Steam Support'), "
                "div[aria-label*='Steam'], "
                "div[role='option']:has-text('Steam'), "
                "xpath=//div[contains(@class, 'customScrollBar')]//div[contains(., 'Steam')], "
                "xpath=//span[contains(text(), 'Steam Support')]"
            )

            msg_clicked = False
            for attempt in range(timeout_seconds // 3):
                # 1. فحص التبويب الحالي
                try:
                    msg = await self.page.query_selector(steam_msg_selector)
                    if msg:
                        await msg.click(force=True)
                        msg_clicked = True
                        logger.info("[OUTLOOK:FOUND] Clicked Steam email message!")
                        break
                except Exception:
                    pass

                # 2. التبديل لتبويب Other إذا كانت الرسالة مصنفة هناك
                if attempt == 3:
                    try:
                        other_tab = await self.page.query_selector("button:has-text('Other'), span:has-text('Other')")
                        if other_tab:
                            await other_tab.click(force=True)
                            logger.info("[OUTLOOK] Switched to 'Other' tab...")
                    except Exception:
                        pass

                # 3. تحديث الصندوق دورياً
                if attempt % 4 == 0 and attempt > 0:
                    try:
                        await self.page.keyboard.press("F5")
                    except Exception:
                        pass

                await asyncio.sleep(3)

            await asyncio.sleep(2.5)

            # قراءة كود التحقق من نص الرسالة المفتوحة
            body_text = await self.page.inner_text("body")

            match = re.search(r"(?:credentials:|code:?)\s*([A-Z0-9]{5})\b", body_text, re.IGNORECASE)
            if match:
                extracted_code = match.group(1).upper()
                logger.info(f"[OUTLOOK:SUCCESS] Extracted verification code: {extracted_code}")
                return extracted_code

            fallback = re.search(r"\b([A-Z0-9]{5})\b", body_text)
            if fallback:
                extracted_code = fallback.group(1).upper()
                logger.info(f"[OUTLOOK:SUCCESS] Fallback extracted code: {extracted_code}")
                return extracted_code

        else:
            # مسار xomail كالمعتاد
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

            await asyncio.sleep(1.5)
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
