import google.generativeai as genai
from app.config import settings
from openai import OpenAI
import base64


class AIService:
    def __init__(self):
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY,
        )

    async def generate_response(
        self, chat_hist: list, context_docs: list = None, image_data_url: str = None
    ):
        # تحويل المعلومات الفنية لنص مفهوم
        context_text = (
            "\n".join(context_docs)
            if context_docs
            else "لا توجد معلومات فنية محددة في قاعدة البيانات حالياً، استخدم خبرتك العامة."
        )

        # البرومبت الجديد: ذكي، مرن، وبيدردش بس بحدود
        system_prompt = f"""
        أنت GearUp AI، مساعد ميكانيكي ذكي وخبير. 
        نطاقك الأساسي هو السيارات، لكنك ودود وتستطيع الدردشة والرد على التحية.

        قواعد الرد:
        1. إذا حياك المستخدم (سلام، أهلاً)، رد بترحيب حار بأسلوب خبير سيارات.
        2. إذا سألك المستخدم في موضوع عام، ساعده بلباقة ثم حاول ربط الحديث بالسيارات إذا أمكن.
        3. عند تحليل عطل (بناءً على المعلومات المتاحة):
           - استخدم المعلومات الفنية المتاحة: {context_text}
           - نسق ردك بـ Markdown ليحتوي على:
             **🔍 التشخيص المحتمل**
             **📊 مستوى التأكد**
             **⚠️ درجة الخطورة**
             **🛠️ خطوات الإصلاح المقترحة**
        4. إذا وجدت صورة، ابدأ بـ "بناءً على الصورة المرفقة..." وحللها بدقة.
        5. في الأعطال الحرجة (محرك، فرامل)، كن حذراً جداً وانصح بالفني المتخصص.
        """

        formatted_messages = [{"role": "system", "content": system_prompt}]

        for msg in chat_hist:
            formatted_messages.append({"role": msg.role, "content": msg.content})

        if image_data_url:
            last_msg_index = -1
            # التأكد من الوصول لآخر رسالة من اليوزر لإضافة الصورة
            for i in range(len(formatted_messages) - 1, -1, -1):
                if formatted_messages[i]["role"] == "user":
                    last_msg_index = i
                    break

            if last_msg_index != -1:
                last_msg_content = formatted_messages[last_msg_index]["content"]
                formatted_messages[last_msg_index]["content"] = [
                    {"type": "text", "text": last_msg_content},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ]

        try:
            response = self.client.chat.completions.create(
                model="google/gemini-2.0-flash-001",
                messages=formatted_messages,
                temperature=0.5,  # رفعنا الحرارة شوية عشان يبقى "أذكى" في الكلام
            )
            return response.choices[0].message.content
        except Exception as e:
            # بنرجع الخطأ الحقيقي عشان نعرف لو الـ API Key فيه مشكلة
            return f"Error from AI Service: {str(e)}"

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
            print(f"Error details: {str(e)}")  # ده هيظهر في الـ Logs
            return f"يا جهاد فيه مشكلة: {str(e)}"  # ده هيظهرلك في الـ Swagger علطول
