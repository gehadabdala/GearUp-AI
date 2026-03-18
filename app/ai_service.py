import json
import base64
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
        # تهيئة الاتصال بـ OpenRouter باستخدام الإعدادات
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
        # تحويل المعلومات الفنية لنص مفهوم
        context_text = (
            "\n".join(context_docs)
            if context_docs
            else "لا توجد معلومات فنية محددة في قاعدة البيانات حالياً، استخدم خبرتك العامة."
        )

        # البرومبت الأساسي: ذكي، مرن، وميكانيكي خبير
        system_prompt = f"""
        أنت GearUp AI، مساعد ميكانيكي محترف، ذكي، وودود.
        نطاقك الأساسي هو السيارات وصيانتها فقط.

        قواعد الرد:
        1. إذا حياك المستخدم (سلام، أهلاً)، رد بترحيب حار بأسلوب خبير سيارات.
        2. إذا كانت الصورة أو النص لا يتعلقان بالسيارات، اعتذر بلباقة موضحاً تخصصك.
        3. عند تحليل عطل (بناءً على المعلومات المتاحة):
           - استخدم المعلومات الفنية والسياق المتاح: {context_text}
           - نسق ردك بـ Markdown ليحتوي على:
             **🔍 التشخيص المحتمل**
             **📊 مستوى التأكد**
             **⚠️ درجة الخطورة**
             **🛠️ خطوات الإصلاح المقترحة**
        4. إذا وجدت صورة مرفقة، ابدأ ردك بتحليل ما تراه فيها تقنياً وبدقة.
        5. في الأعطال الحرجة (محرك، فرامل)، كن حذراً جداً وانصح بالفني المتخصص.
        """

        formatted_messages = [{"role": "system", "content": system_prompt}]

        # إضافة تاريخ المحادثة
        for msg in chat_hist:
            formatted_messages.append({"role": msg.role, "content": msg.content})

        # معالجة الصورة إذا وجدت وإضافتها لآخر رسالة مستخدم
        if image_data_url:
            last_msg_index = -1
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
                model=self.DEFAULT_MODEL,
                messages=formatted_messages,
                temperature=0.5,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[AI Generate Error]: {e}")
            return f"عذراً يا جيهاد، واجهت مشكلة تقنية: {str(e)}"

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
            return f"خطأ في قراءة الصورة: {str(e)}"

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
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
            )

            result_text = response.choices[0].message.content
            clean_json_text = (
                result_text.replace("```json", "").replace("```", "").strip()
            )
            return json.loads(clean_json_text)

        except Exception as e:
            print(f"[Specialty Extraction Error]: {e}")
            return {"specialty": "ميكانيكا", "sub_specialty": "موتور"}
