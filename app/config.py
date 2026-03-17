# الإعدادات و API Keys

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # 1. إعدادات الذكاء الاصطناعي
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

    # 2. إعدادات قاعدة بيانات الميكانيكية
    DB_SERVER = os.getenv("DB_SERVER")
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")

    # 3. إعدادات مصدر البيانات
    SHEET_ID = os.getenv("SHEET_ID")
    FILE_PATH = os.getenv("FILE_PATH")

    SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv" if SHEET_ID else None

    # 4. إعدادات ثابتة مش محتاجة تتغير
    CHROMA_PATH = "./chroma_db"
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"

settings = Settings()
