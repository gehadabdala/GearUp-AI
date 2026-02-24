from google import genai
from app.config import settings

class AIService:
    def __init__(self):
        # المكتبة الجديدة بتعرف تتعامل مع المفتاح بتاعك تلقائياً
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        # هنستخدم الموديل اللي شفته شغال عندك في الـ Studio
        self.model_id = "gemini-1.5-flash-latest"

    async def generate_response(self, user_query: str, context_docs: list):
        # تحويل القائمة لنص بسيط
        context_text = "\n".join(context_docs)
        
        prompt = f"أنت خبير سيارات. بناءً على هذه المعلومات: {context_text}\nأجب على: {user_query}"
        
        try:
            # نداء مباشر وبسيط جداً
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt
            )
            return response.text
        except Exception as e:
            # لو حصل أي مشكلة، هنرجع "أول نتيجة" من قاعدة البيانات كحل احتياطي
            if context_docs:
                return f"عذراً، واجهت مشكلة في التعبير ولكن الحل المقترح هو: {context_docs[0]}"
            return f"خطأ في الاتصال: {str(e)}"