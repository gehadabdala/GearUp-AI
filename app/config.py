# الإعدادات و API Keys

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    NaraRouter_key = os.getenv("NaraRouter_key")
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

    USE_LOCAL_AI = os.getenv("USE_LOCAL_AI") == "True"
    LOCAL_THINKER_MODEL = os.getenv("LOCAL_THINKER_MODEL", "llama3")


settings = Settings()
