import json
from openai import OpenAI
from app.config import settings


class AIService:
    """
    خدمة الذكاء الاصطناعي المسؤولة عن التواصل مع نماذج اللغة
    عبر OpenRouter لتحليل الأعطال واستخراج البيانات.
    """

    # تحديد الموديل كمتغير ثابت لسهولة التعديل مستقبلاً
    DEFAULT_MODEL = "google/gemini-2.0-flash-001"

    def __init__(self):
        # تهيئة الاتصال بـ OpenRouter
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY,
        )

    async def generate_response(
            self, chat_hist: list, context_docs: list = None, image_data_url: str = None
    ) -> str:
        """
        توليد رد الذكاء الاصطناعي بناءً على تاريخ المحادثة، السياق، والصور المرفقة.
        """
        context_text = (
            "\n".join(context_docs) if context_docs else "لا توجد معلومات إضافية."
        )

        # تم تعديل الـ System Prompt ليكون مرناً ويتوافق مع القوالب المرسلة من main.py
        system_prompt = f"""
        أنت GearUp AI، مساعد ميكانيكي محترف، ذكي، وودود.
        نطاق عملك: صيانة السيارات فقط.

        قواعد أساسية:
        1. إذا كانت الصورة أو النص لا يتعلقان بالسيارات، اعتذر بلباقة موضحاً تخصصك.
        2. التزم دائماً بالتنسيق والتعليمات الموجهة إليك في الرسالة الأخيرة (المشكلة).
        3. إذا وجدت صورة مرفقة، ابدأ ردك بتحليل ما تراه فيها تقنياً.

        المعلومات الفنية والسياق المتاح:
        {context_text}
        """

        formatted_messages = [{"role": "system", "content": system_prompt}]

        # إضافة تاريخ المحادثة
        for msg in chat_hist:
            formatted_messages.append({"role": msg.role, "content": msg.content})

        # معالجة الصورة إذا وجدت
        if image_data_url:
            last_msg_content = formatted_messages[-1]["content"]
            formatted_messages[-1]["content"] = [
                {"type": "text", "text": last_msg_content},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]

        try:
            response = self.client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                messages=formatted_messages,
                temperature=0.2,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[AI Generate Error]: {e}")
            return "عذراً، واجهت مشكلة تقنية في تحليل العطل. يرجى المحاولة مرة أخرى."

    async def get_ocr_text(self, prompt: str, image_data_url: str) -> str:
        """
        قراءة النصوص من الصور (مثل الرخص والبطاقات) باستخدام الذكاء الاصطناعي.
        """
        try:
            response = self.client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    }
                ],
                temperature=0.1,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[OCR Error]: {e}")
            return ""

    async def extract_specialty(self, description: str, suggested_part: str) -> dict:
        """
        تحليل وصف المشكلة لاستخراج التخصص والتخصص الدقيق بصيغة JSON.
        """
        available_specialties = """
        - ميكانيكا (موتور، فتيس، دورة تبريد)
        - عفشة (فرامل، مساعدين، دركسيون)
        - كهرباء (بطارية، مارش، ضفيرة، حساسات)
        - تكييف (كمبروسر، شحن فريون)
        """

        system_prompt = "You are a data extraction API. Output ONLY raw JSON format. No markdown formatting, no explanations."

        user_prompt = f"""
        صنف المشكلة التالية إلى تخصص وتخصص دقيق بناءً على القائمة المتاحة فقط.

        المشكلة: {description}
        القطعة المرتبطة: {suggested_part}

        القائمة المتاحة:
        {available_specialties}

        يجب أن ترد بصيغة JSON فقط بهذا الشكل الدقيق:
        {{"specialty": "اسم التخصص هنا", "sub_specialty": "اسم التخصص الدقيق هنا"}}
        """

        try:
            response = self.client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0,  # صفر لمنع الهلوسة خارج الـ JSON
            )

            result_text = response.choices[0].message.content

            # تنظيف الرد لضمان نجاح التحويل إلى قاموس (Dictionary)
            clean_json_text = result_text.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_json_text)

        except Exception as e:
            print(f"[Specialty Extraction Error]: {e}")
            # قيم افتراضية آمنة في حالة الفشل
            return {"specialty": "ميكانيكا", "sub_specialty": "موتور"}