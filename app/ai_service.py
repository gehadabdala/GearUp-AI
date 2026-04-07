import json
import base64
from openai import OpenAI
from app.models import Message
from app.config import settings
from datetime import datetime, timedelta
from app.local_llm import simple_llm_service


class AIService:
    """
    خدمة الذكاء الاصطناعي المسؤولة عن التواصل مع نماذج اللغة
    عبر OpenRouter لتحليل الأعطال واستخراج البيانات.
    """

    # الموديل المستقر
    # DEFAULT_MODEL = "google/gemini-2.0-flash-001"
    DEFAULT_MODEL = "openrouter/auto"

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
            print(f"❌ [AI Generate Error]: {e} - Falling back to local model...")
            try:
                prompt = ""
                for msg in formatted_messages:
                    if isinstance(msg["content"], list):
                        text_parts = [
                            p["text"] for p in msg["content"] if p["type"] == "text"
                        ]
                        content = " ".join(text_parts)
                    else:
                        content = msg["content"]

                    role = (
                        "Assistant"
                        if msg["role"] == "assistant"
                        else "User" if msg["role"] == "user" else "System"
                    )
                    prompt += f"{role}: {content}\n"
                prompt += "Assistant: "

                return simple_llm_service.generate(
                    prompt=prompt, max_tokens=512, temperature=0.5
                )
            except Exception as local_e:
                print(f"❌ [Local LLM Generate Error]: {local_e}")
                return "عذراً، واجهت الخوادم الرئيسية والبديلة مشكلة تقنية. يرجى المحاولة لاحقاً."

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
        except Exception as e:
            print(f"❌ [AI Extract Error]: {e} - Falling back to local model...")
            try:
                prompt = f"System: {system_prompt}\nUser: {user_prompt}\nAssistant: "
                local_resp = simple_llm_service.generate(
                    prompt=prompt, max_tokens=200, temperature=0.0
                )
                clean_json = (
                    local_resp.replace("```json", "").replace("```", "").strip()
                )
                return json.loads(clean_json)
            except Exception as local_e:
                print(f"❌ [Local LLM Extract Error]: {local_e}")
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
        except Exception as e:
            print(
                f"❌ [AI Extract Reminder Error]: {e} - Falling back to local model..."
            )
            try:
                local_prompt = f"User: {prompt}\nAssistant: "
                local_resp = simple_llm_service.generate(
                    prompt=local_prompt, max_tokens=300, temperature=0.0
                )
                clean_json = (
                    local_resp.replace("```json", "").replace("```", "").strip()
                )
                return json.loads(clean_json)
            except Exception as local_e:
                print(f"❌ [Local LLM Extract Reminder Error]: {local_e}")
                return {
                    "title": "تذكير صيانة",
                    "description": "فحص دوري للسيارة",
                    "frequency": "مرة واحدة فقط",
                    "suggested_date": (datetime.now() + timedelta(days=7)).strftime(
                        "%Y/%m/%d"
                    ),
                    "notification_time": "10:00 AM",
                }

    # --- إضافة جديدة لتحقيق الـ FR-5 والـ FR-6 ---
    async def get_personalized_recommendations(
        self, user_car_model: str, problem_type: str
    ) -> dict:
        """
        بناءً على موديل العربية (FR-5) ونوع المشكلة، بنقترح ميكانيكي وقطع غيار (FR-6)
        """
        prompt = f"""
    المستخدم عنده عربية {user_car_model} وبيشتكي من {problem_type}.
    1. اقترح تخصص الميكانيكي المناسب.
    2. اقترح قطع الغيار اللي ممكن يحتاجها.
    3. هات لينكات بحث (Search Links) لقطع الغيار دي على Amazon.eg.
    رد بصيغة JSON فقط.
    """
        try:
            # بننادي على الموديل اللي إنتي مثبتاه (OpenRouter Auto)
            response = self.client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )

            return json.loads(response.choices[0].message.content)
        except:
            # لو حصل أي مشكلة، بنرجع داتا فاضية وما بنبوظش السيرفر
            return {"suggested_parts": [], "mechanic_type": "عام"}
