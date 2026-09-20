FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# تنصيب المتصفح مع كل الملفات الأساسية اللي يحتاجها بالسحابة
RUN playwright install --with-deps chromium
COPY . .
# تشغيل سيرفر المايسترو
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]