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
    # DEFAULT_MODEL = "google/gemma-4-31b-it"

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
                أنت "GearUp AI"، المساعد الذكي وخبير السيارات الخاص بمنصة GearUp.
                شخصيتك: أنت صديق ودود جداً، محترف، ومتعاطف. تتحدث بلغة عربية سلسة ومريحة (فصحى مبسطة مطعمة بمصطلحات السيارات المألوفة).

                قواعد الرد الأساسية:
                1. الترحيب والأسلوب: ابدأ دائماً بترحيب دافئ (استخدم إيموجيز مناسبة مثل 🚗، 🔧، 💡، ✨ بشكل لطيف وغير مبالغ فيه).
                2. التعاطف: إذا كان المستخدم يعاني من مشكلة في سيارته، أظهر تعاطفك وتفهمك للموقف (مثل: "لا تقلق، نحن هنا للمساعدة").
                3. الطوارئ والأعطال الحرجة (مثل: ارتفاع حرارة المحرك للدرجة القصوى، تعطل الفرامل، خروج أدخنة، أو تسريب وقود): حافظ على نبرة هادئة جداً ومطمئنة ("سلامتك هي الأهم، لا تقلق"). تجنب إثارة الذعر تماماً، وقدم خطوات أمان فورية ومباشرة لحماية السائق والسيارة.
                4. التخصص: نطاقك هو السيارات وصيانتها فقط. إذا كان الموضوع خارج ذلك، اعتذر بلباقة ومرح ووجهه للحديث عن سيارته.
                5. التنسيق: استخدم القوائم، الخط العريض، والمسافات (Markdown) لجعل إجاباتك مريحة للعين.

                استخدم هذه المعلومات الفنية كأساس لردك:
                {context_text}
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
                - ميكانيكا (موتور، فتيس، دورة تبريد، رادياتير، شكمان)
                - عفشة (فرامل، تيل، طنابير، مساعدين، دركسيون، كبالن)
                - كهرباء (بطارية، مارش، دينامو، ضفيرة، حساسات، إضاءة)
                - تكييف (كمبروسر، شحن فريون، تسريب)
                - سمكرة (خبطات، حوادث، استعدال شاسيه)
                - دوكو (دهان، رش، تلميع)
                - كاوتش (نفخ، ترصيص، زوايا، لحام)
                - زجاج (تغيير زجاج، لحام شروخ)
                - مفاتيح وأقفال (برمجة مفاتيح، سنتر لوك)
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

    # 4. محرك تحليل النية (Intent Classifier) - الإضافة الجديدة
    async def analyze_intent(self, user_message: str) -> dict:
        system_prompt = "You are a specialized automotive intent classifier. Output ONLY raw JSON. No markdown."
        user_prompt = f"""
                قم بتحليل رسالة المستخدم التالية المتعلقة بالسيارات لتحديد مسار الواجهة الأمامية (Frontend) بدقة قاطعة.
                رسالة المستخدم: "{user_message}"

                قم بإرجاع JSON فقط يحتوي على الحقول المنطقية (true أو false) التالية:
                {{
                    "is_emergency": "true فقط في حالات الخطر الداهم التي تتطلب توقف فوري لحماية حياة السائق أو المحرك (أمثلة حصرية: سخونة المحرك القصوى، عطل الفرامل، خروج دخان، تسريب وقود أو زيت شديد). في أي عطل آخر، اجعلها false.",
                    "needs_mechanic": "true في أي حالة تتطلب فحص بورشة أو تدخل فني (هذا يشمل جميع حالات الطوارئ السابقة، ويشمل أيضاً الأعطال غير الخطيرة مثل: تكييف لا يعمل، فتيس يعلق، صوت في العفشة). إذا كانت مجرد استشارة، اجعلها false.",
                    "is_advice": "true فقط إذا كان المستخدم يطلب نصيحة، مواعيد صيانة، أو يسأل عن أسعار/أنواع (مثل: متى أغير الزيت، أفضل نوع كاوتش). وإلا false.",
                    "is_greeting": "true فقط إذا كانت الرسالة مجرد تحية أو تعارف (مثل: السلام عليكم، من أنت). وإلا false."
                }}
        """

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
            print(f"❌ [Intent Analysis Error]: {e}")
            # قيم احتياطية في حالة حدوث عطل
            return {
                "is_emergency": False,
                "is_advice": False,
                "is_greeting": False,
                "needs_mechanic": False
            }