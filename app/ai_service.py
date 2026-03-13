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

    async def generate_response(
        self, chat_hist: list, context_docs: list = None, image_data_url: str = None
    ):
        context_text = (
            "\n".join(context_docs) if context_docs else "لا توجد معلومات فنية محددة."
        )

        system_prompt = f"""
        أنت GearUp AI، مساعد ميكانيكي محترف وصارم.
        نطاق عملك: صيانة السيارات فقط.
        
        قواعد الرد الإلزامية:
        1. إذا كانت الصورة أو النص لا يتعلقان بأعطال السيارات، اعتذر فوراً (أنا متخصص في السيارات فقط).
        2. إذا وجدت صورة، ابدأ ردك بعبارة "بناءً على الصورة المرفقة..." وقم بتحليلها تقنياً.
        3. يجب أن يحتوي الرد على العناصر التالية بتنسيق Markdown:
           - **🔍 التشخيص المحتمل (Potential Fault):** اسم العطل.
           - **📊 مستوى التأكد (Confidence Level):** نسبة مئوية.
           - **⚠️ درجة الخطورة (Urgency Status):** (Low/Medium/High).
           - **🛠️ خطوات الإصلاح:** في نقاط واضحة.
        
        المعلومات الفنية المتاحة: {context_text}
        """

        formatted_messages = [{"role": "system", "content": system_prompt}]

        for msg in chat_hist:
            formatted_messages.append({"role": msg.role, "content": msg.content})

        if image_data_url:
            last_msg_content = formatted_messages[-1]["content"]
            formatted_messages[-1]["content"] = [
                {"type": "text", "text": last_msg_content},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]

        try:
            response = self.client.chat.completions.create(
                model="google/gemini-2.0-flash-001",
                messages=formatted_messages,
                temperature=0.2,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Error: {e}")
            return "عذراً، أنا GearUp AI. واجهت مشكلة في تحليل العطل. يرجى وصف المشكلة بوضوح."

    async def get_ocr_text(self, prompt: str, image_data_url: str):
        try:
            response = self.client.chat.completions.create(
                model="google/gemini-2.0-flash-001",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    }
                ],
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"OCR Error: {str(e)}")
            return ""
