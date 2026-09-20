import asyncio
import re
from playwright.async_api import BrowserContext

async def fetch_code_from_xomail(context: BrowserContext, email: str, password: str, timeout_seconds: int = 60) -> str:
    page = await context.new_page()
    try:
        # 1. الدخول لصفحة البريد
        await page.goto("http://xomail.club/", wait_until="domcontentloaded", timeout=20000)

        # 2. تسجيل الدخول باستخدام المحددات المأخوذة من الفحص
        await page.fill("#rcmloginuser", email)
        await page.fill("#rcmloginpwd", password)
        await page.click("#rcmloginsubmit")

        # انتظار تحميل الواجهة الرئيسية لصندوق البريد
        await page.wait_for_selector("table#messagelist", timeout=20000)

        # 3. محاولة العثور على الرسالة وعمل Refresh بشكل متكرر
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout_seconds:
            # التحقق من وجود رسائل في الصندوق
            messages = await page.query_selector_all("table#messagelist tr.message")
            if messages:
                # فتح أول رسالة وصلت
                await messages[0].click()
                await asyncio.sleep(2)

                # قراءة محتوى الرسالة (سواء كانت بنص مباشر أو داخل iframe)
                content = ""
                iframe_element = await page.query_selector("#messagecontframe")
                if iframe_element:
                    frame = await iframe_element.content_frame()
                    if frame:
                        content = await frame.content()
                
                if not content:
                    content = await page.content()

                # استخراج كود ستيم المكون من 5 أحرف وأرقام بالعادة
                match = re.search(r'\b([A-Z0-9]{5})\b', content)
                if match:
                    return match.group(1)

            # الضغط على زر التحديث في حال لم تصل الرسالة بعد
            refresh_btn = await page.query_selector("a.toolbar-button.refresh")
            if refresh_btn:
                await refresh_btn.click()

            await asyncio.sleep(4)

        raise TimeoutError("لم يتم العثور على رسالة التحقق خلال الوقت المحدد.")

    finally:
        await page.close()
