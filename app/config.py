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



