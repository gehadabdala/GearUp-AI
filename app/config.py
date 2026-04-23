# الإعدادات و API Keys

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    DB_SERVER = os.getenv("DB_SERVER")
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")

    SHEET_ID = os.getenv("SHEET_ID")

    SHEET_URL = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
        if SHEET_ID
        else None
    )

    CHROMA_PATH = "./chroma_db"
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"

settings = Settings()
