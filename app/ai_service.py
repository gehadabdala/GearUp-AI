import json
import base64
from openai import OpenAI
from app.models import Message
from app.config import settings
from datetime import datetime, timedelta


# =====================================================================
# [ 1. خدمة الذكاء الاصطناعي (AI Service Core) ]
# =====================================================================
class AIService:
    """
    خدمة الذكاء الاصطناعي المسؤولة عن التواصل مع نماذج اللغة
    عبر OpenRouter لتحليل الأعطال واستخراج البيانات.
    """

    # تحديد الموديل كمتغير ثابت لسهولة التعديل مستقبلاً
    DEFAULT_MODEL = "google/gemini-2.0-flash-001"

    def __init__(self):
        # 2. التغيير السحري هنا: بنروح لـ base_url بتاع جوجل مباشرة
        # ده بيخلي مكتبة openai "تتكلم" مع جوجل فوراً
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY,
        )


    # =====================================================================
    # [ 2. محرك الدردشة والتشخيص (Chat & Diagnostics Engine) ]
    # =====================================================================
    async def generate_response(
        self, chat_hist: list, context_docs: list = None, image_data_url: str = None
    ) -> str:
        """
        توليد رد الذكاء الاصطناعي بناءً على تاريخ المحادثة، السياق، والصور المرفقة.
        """
        # 1. تحويل المعلومات الفنية (السياق) لنص مفهوم للـ AI
        context_text = (
            "\n".join(context_docs)
            if context_docs
            else "لا توجد معلومات فنية محددة في قاعدة البيانات حالياً، استخدم خبرتك العامة."
        )

        # 2. هندسة الأوامر (Prompt Engineering): تحديد شخصية وقواعد الـ AI
        system_prompt = f"""
                أنت GearUp AI، مساعد ميكانيكي محترف، ذكي، وودود.
                نطاقك الأساسي هو السيارات وصيانتها فقط.

                قواعد الرد:
                1. إذا حياك المستخدم (سلام، أهلاً)، رد بترحيب حار بأسلوب خبير سيارات.
                2. إذا كانت الصورة أو النص لا يتعلقان بالسيارات، اعتذر بلباقة موضحاً تخصصك.
                3. استخدم المعلومات الفنية والسياق المتاح لدعم إجابتك: {context_text}
                4. التزم "بالتنسيق والتعليمات" الموجهة إليك في نهاية الرسالة بدقة (سواء كان المطلوب تشخيص عطل معقد أو مجرد نصيحة ودية).
                5. في الأعطال الحرجة (محرك، فرامل)، كن حذراً جداً وانصح بالفني المتخصص.
                """

        # 3. بناء مصفوفة الرسائل (Messages Payload)
        formatted_messages = [{"role": "system", "content": system_prompt}]

        # إضافة الهيستوري الخاص بالمستخدم
        for msg in chat_hist:
            formatted_messages.append({"role": msg.role, "content": msg.content})

        # 4. معالجة الرؤية البصرية (Vision): دمج الصورة مع آخر رسالة للمستخدم
        if image_data_url:
            last_msg_index = -1
            # البحث عن آخر رسالة من المستخدم (من الخلف للأمام)
            for i in range(len(formatted_messages) - 1, -1, -1):
                if formatted_messages[i]["role"] == "user":
                    last_msg_index = i
                    break

            if last_msg_index != -1:
                last_msg_content = formatted_messages[last_msg_index]["content"]
                # تعديل الهيكل ليقبل نص + صورة معاً
                formatted_messages[last_msg_index]["content"] = [
                    {"type": "text", "text": last_msg_content},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ]

        try:
            # 5. إرسال الطلب (Temperature 0.5 للإبداع المتزن في الشات)
            response = self.client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                messages=formatted_messages,
                temperature=0.5,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"❌ [AI Generate Error]: {e}")
            return "عذراً، واجهت مشكلة تقنية في الخادم. يرجى المحاولة مرة أخرى لاحقاً."


    # =====================================================================
    # [ 3. محرك قراءة المستندات (Vision & OCR) ]
    # =====================================================================
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
                temperature=0.1, # نستخدم Temperature 0.1 لضمان الدقة العالية وعدم التأليف (Hallucination) في قراءة الأرقام
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[OCR Error]: {e}")
            return f"خطأ في قراءة الصورة: {str(e)}"


    # =====================================================================
    # [ 4. محرك استخراج البيانات المهيكلة (Structured Data Extraction) ]
    # =====================================================================
    async def extract_specialty(self, description: str, suggested_part: str) -> dict:
        """
        تحليل وصف المشكلة واستخراج (التخصص) و (التخصص الدقيق) بصيغة JSON.
        يُستخدم هذا لربط العطل بأفضل فني مناسب في قاعدة البيانات.
        """

        available_specialties = """
        - ميكانيكا (موتور، فتيس، دورة تبريد)
        - عفشة (فرامل، مساعدين، دركسيون)
        - كهرباء (بطارية، مارش، ضفيرة، حساسات)
        - تكييف (كمبروسر، شحن فريون)
        """

        # إجبار الـ AI على إرجاع JSON خام بدون أي تنسيقات Markdown
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
            # نستخدم Temperature 0.0 لضمان خروج الـ JSON بنفس الهيكل دائماً
            response = self.client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
            )

            result_text = response.choices[0].message.content
            # تنظيف الرد من أي علامات Markdown قد يضيفها الموديل بالغلط
            clean_json_text = result_text.replace("```json", "").replace("```", "").strip()

            return json.loads(clean_json_text)

        except Exception as e:
            print(f"❌ [Specialty Extraction Error]: {e}")
            # Fallback (قيمة احتياطية) في حالة فشل التحليل حتى لا يتوقف النظام
            return {"specialty": "ميكانيكا", "sub_specialty": "موتور"}


    # =====================================================================
    # [ 5. محرك استخراج بيانات التذكير (Reminder Data Extraction) ]
    # =====================================================================
    async def extract_reminder_details(self, ai_answer: str) -> dict:
        """
        هذه الدالة تجبر الـ AI على تحويل النص المرسل للمستخدم إلى بيانات مجدولة.
        """
        prompt = f"""
        بناءً على هذا الرد: "{ai_answer}"
        استخرج بيانات التذكير في شكل JSON حصراً كالتالي:
        {{
          "title": "عنوان قصير للتذكير",
          "description": "وصف مختصر",
          "frequency": "مرة واحدة / يومي / أسبوعي / شهري / كل 6 أشهر",
          "suggested_date": "تاريخ البداية بتنسيق YYYY/MM/DD (لو لم يذكر، افترض أنه بعد أسبوع من اليوم)",
          "notification_time": "الوقت بتنسيق HH:MM AM/PM"
        }}
        ملاحظة: اليوم هو {datetime.now().strftime('%Y/%m/%d')}.
        """

        try:
            # بننادي الـ AI تاني بس بـ Prompt مخصص للاستخراج
            response = await self.generate_response([Message(role="user", content=prompt)])
            # تنظيف الرد من أي علامات Markdown عشان نعرف نحوله لـ Dictionary
            clean_json = response.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_json)
        except:
            # لو فشل، بنرجع قيم افتراضية بدل الـ Null
            return {
                "title": "تذكير صيانة",
                "description": ai_answer[:50],
                "frequency": "مرة واحدة فقط",
                "suggested_date": (datetime.now() + timedelta(days=7)).strftime("%Y/%m/%d"),
                "notification_time": "10:00 AM"
            }