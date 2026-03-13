# الإعدادات و API Keys

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # حطي المفتاح هنا مباشرة من غير os.k-or-v1-3cc869a8getenv عشان نختبر
    OPENROUTER_API_KEY = (
        "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"
    )
    CHROMA_PATH = "./chroma_db"
    # استخدمي حرف r قبل المسار عشان الـ Backslashes ما تعملش مشكلة في ويندوز
    EXCEL_PATH = r"F:\gearup_recommendation\data\CarFaults_50000.xlsx"
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"


settings = Settings()
