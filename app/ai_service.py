import json
import base64
from openai import OpenAI
from app.models import Message
from app.config import settings
from datetime import datetime, timedelta


class AIService:
    """
    خدمة الذكاء الاصطناعي المسؤولة عن التواصل مع نماذج اللغة
    عبر OpenRouter لتحليل الأعطال واستخراج البيانات.
    """

    # الموديل المستقر
    DEFAULT_MODEL = "google/gemini-2.0-flash-001"

    def __init__(self):
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY,
        )

    # 1. محرك الدردشة والتشخيص
    async def generate_response(
        self, chat_hist: list, context_docs: list = None, image_data_url: str = None
    ) -> str:
        context_text = (
            "\n".join(context_docs)
            if context_docs
            else "لا توجد معلومات فنية محددة في قاعدة البيانات حالياً، استخدم خبرتك العامة."
        )

        system_prompt = f"""
                أنت GearUp AI، مساعد ميكانيكي محترف، ذكي، وودود.
                نطاقك الأساسي هو السيارات وصيانتها فقط.
                قواعد الرد:
                1. إذا حياك المستخدم، رد بترحيب حار بأسلوب خبير سيارات.
                2. إذا كان الموضوع خارج السيارات، اعتذر بلباقة.
                3. استخدم المعلومات الفنية: {context_text}
                4. في الأعطال الحرجة، انصح بالفني المتخصص فوراً.
                """

        formatted_messages = [{"role": "system", "content": system_prompt}]
        for msg in chat_hist:
            formatted_messages.append({"role": msg.role, "content": msg.content})

        if image_data_url:
            for i in range(len(formatted_messages) - 1, -1, -1):
                if formatted_messages[i]["role"] == "user":
                    last_content = formatted_messages[i]["content"]
                    formatted_messages[i]["content"] = [
                        {"type": "text", "text": last_content},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ]
                    break

        try:
            response = self.client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                messages=formatted_messages,
                temperature=0.5,
                max_tokens=512,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"❌ [AI Generate Error]: {e}")
            return "عذراً، واجهت مشكلة تقنية. يرجى المحاولة لاحقاً."

    # 2. محرك استخراج التخصص (الربط مع الميكانيكي)
    async def extract_specialty(self, description: str, suggested_part: str) -> dict:
        available_specialties = """
        - ميكانيكا (موتور، فتيس، دورة تبريد)
        - عفشة (فرامل، مساعدين، دركسيون)
        - كهرباء (بطارية، مارش، ضفيرة، حساسات)
        - تكييف (كمبروسر، شحن فريون)
        """
        system_prompt = (
            "You are a data extraction API. Output ONLY raw JSON. No markdown."
        )
        user_prompt = f"""صنف المشكلة: {description} | القطعة: {suggested_part}
        القائمة: {available_specialties}
        رد بصيغة JSON: {{"specialty": "...", "sub_specialty": "..."}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=200,
            )
            clean_json = (
                response.choices[0]
                .message.content.replace("```json", "")
                .replace("```", "")
                .strip()
            )
            return json.loads(clean_json)
        except:
            return {"specialty": "ميكانيكا", "sub_specialty": "عام"}

    # 3. محرك استخراج بيانات التذكير
    async def extract_reminder_details(self, ai_answer: str) -> dict:
        prompt = f"""
        بناءً على الرد: "{ai_answer}"
        استخرج بيانات التذكير بتنسيق JSON:
        {{
          "title": "عنوان",
          "description": "وصف",
          "frequency": "مرة واحدة / يومي / أسبوعي / شهري",
          "suggested_date": "YYYY/MM/DD",
          "notification_time": "HH:MM AM/PM"
        }}
        اليوم هو {datetime.now().strftime('%Y/%m/%d')}.
        """
        try:
            response = self.client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=300,
            )
            clean_json = (
                response.choices[0]
                .message.content.replace("```json", "")
                .replace("```", "")
                .strip()
            )
            return json.loads(clean_json)
        except:
            return {
                "title": "تذكير صيانة",
                "description": "فحص دوري للسيارة",
                "frequency": "مرة واحدة فقط",
                "suggested_date": (datetime.now() + timedelta(days=7)).strftime(
                    "%Y/%m/%d"
                ),
                "notification_time": "10:00 AM",
            }
