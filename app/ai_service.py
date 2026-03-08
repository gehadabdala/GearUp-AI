import google.generativeai as genai
from app.config import settings
from openai import OpenAI

class AIService:
    def __init__(self):
      # الربط بـ OpenRouter باستخدام مكتبة OpenAI
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY, 
        )
    async def generate_response(self, user_query: str, context_docs: list = None):
        # 1. تحويل القائمة لنص بسيط
        context_text = "\n".join(context_docs) if context_docs else "لا توجد معلومات فنية محددة."
        
        prompt = (
            f"أنت GearUp AI، مساعد ذكي متخصص **فحص حصري** في صيانة وأعطال السيارات فقط.\n"
            f"نطاق عملك: تقديم حلول ميكانيكية بناءً على هذه المعلومات: {context_text}\n"
            f"قاعدة صارمة: إذا سألك المستخدم عن أي شيء خارج عالم السيارات (مثل المطاعم، الطبخ، الرياضة، إلخ)، "
            f"يجب عليك الاعتذار فوراً وتوضيح أن تخصصك هو 'السيارات فقط' ولا تقدم أي نصائح أخرى.\n"
            f"سؤال المستخدم: {user_query}"
        )
        
        try:
            # 3. نداء الموديل
            response = self.client.chat.completions.create(
                #model="openai/gpt-3.5-turbo",
                model="google/gemini-2.0-flash-001",
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
         # استخراج النص من الرد
            return response.choices[0].message.content
        
        except Exception as e:
            # طباعة الخطأ في التيرمينال عشان نعرف لو الـ API مفتاحها غلط
            print(f"OpenRouter Error: {str(e)}")
            return "أهلاً بك! أنا GearUp، مساعدك الذكي للسيارات. كيف يمكنني مساعدتك اليوم؟"
        



        # الدالة الجديدة الخاصة بالـ OCR فقط
    async def get_ocr_text(self, prompt: str, image_data_url: str):
        try:
            response = self.client.chat.completions.create(
                model="google/gemini-2.0-flash-001", # موديل سريع ودقيق في الصور
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": image_data_url}
                            },
                        ],
                    }
                ],
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"OCR Error: {str(e)}")
            return ""