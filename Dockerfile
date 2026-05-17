FROM python:3.11-slim

# تعريف مسار العمل
WORKDIR /app

# نسخ ملف المكاتب وتسطيبها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع
COPY . .

# إعطاء صلاحيات للمجلد عشان ChromaDB يشتغل براحته
RUN chmod -R 777 /app

# تشغيل السيرفر على بورت 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]