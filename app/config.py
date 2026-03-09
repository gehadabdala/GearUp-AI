 # الإعدادات و API Keys

import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # حطي المفتاح هنا مباشرة من غير os.k-or-v1-3cc869a8getenv عشان نختبر
    OPENROUTER_API_KEY = "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"
    CHROMA_PATH = "./chroma_db"
    # استخدمي حرف r قبل المسار عشان الـ Backslashes ما تعملش مشكلة في ويندوز
    EXCEL_PATH = r"F:\gearup_recommendation\data\CarFaults_50000.xlsx"
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"
settings = Settings()
