FROM python:3.11-slim

# 1. فولدر السيرفر الأساسي
WORKDIR /code

# 2. تعريف المسار لبايثون
ENV PYTHONPATH=/code

# 3. تسطيب المكاتب
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. نسخ كل ملفاتك (بما فيها فولدر app و chroma_db) لـ /code
COPY . .

# 5. صلاحيات القراءة والكتابة
RUN chmod -R 777 /code

# 6. أمر التشغيل الصحيح (بيدخل فولدر app ويشغل main)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]