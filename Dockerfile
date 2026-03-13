# استخدام نسخة بايثون خفيفة
FROM python:3.10-slim

# تحديد فولدر الشغل جوه السيرفر
WORKDIR /app

# نسخ ملف المكتبات أولاً
COPY requirements.txt .

# تثبيت المكتبات
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع
COPY . .

# فتح البورت 8000
EXPOSE 8000

# أمر تشغيل السيرفر
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]