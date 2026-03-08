 # الإعدادات و API Keys

import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # حطي المفتاح هنا مباشرة من غير os.getenv عشان نختبر
    OPENROUTER_API_KEY = "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"
    CHROMA_PATH = "./chroma_db"
    # استخدمي حرف r قبل المسار عشان الـ Backslashes ما تعملش مشكلة في ويندوز
    EXCEL_PATH = r"F:\gearup_recommendation\data\CarFaults_50000.xlsx"
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"
settings = Settings()
