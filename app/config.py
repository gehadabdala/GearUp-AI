 # الإعدادات و API Keys

import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # حطي المفتاح هنا مباشرة من غير os.getenv عشان نختبر
    GEMINI_API_KEY = "AIzaSyBZTnzIrt-1SB0Yk0aaQRbhjVmJ-egRo1E" 
    CHROMA_PATH = "./chroma_db"
    # استخدمي حرف r قبل المسار عشان الـ Backslashes ما تعملش مشكلة في ويندوز
    EXCEL_PATH = r"F:\gearup_recommendation\data\CarFaults_50000.xlsx"
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"
settings = Settings()



