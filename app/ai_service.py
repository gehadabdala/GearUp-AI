import json
import base64
from openai import AsyncOpenAI
from app.models import Message
from app.config import settings
import urllib.parse


class AIService:
    """
    خدمة الذكاء الاصطناعي المسؤولة عن التواصل مع نماذج اللغة
    عبر OpenRouter لتحليل الأعطال واستخراج البيانات.
    """

    DEFAULT_MODEL = "google/gemini-2.0-flash-001"

    def __init__(self):
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY,
        )

    # =====================================================================
    # [ 2. محرك الدردشة والتشخيص (Chat & Diagnostics Engine) ]
    # =====================================================================
    async def generate_response(
            self, chat_hist: list, context_docs: list = None, image_data_urls: list = None
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
                3. الطوارئ والأعطال الحرجة: حافظ على نبرة هادئة جداً ومطمئنة ("سلامتك هي الأهم، لا تقلق"). تجنب إثارة الذعر تماماً، وقدم خطوات أمان فورية ومباشرة لحماية السائق والسيارة.
                4. التخصص: نطاقك هو السيارات وصيانتها فقط. إذا كان الموضوع خارج ذلك، اعتذر بلباقة ومرح ووجهه للحديث عن سيارته.
                5. التنسيق: استخدم القوائم، الخط العريض، والمسافات (Markdown) لجعل إجاباتك مريحة للعين.

                استخدم هذه المعلومات الفنية كأساس لردك:
                {context_text}
                """

        formatted_messages = [{"role": "system", "content": system_prompt}]
        for msg in chat_hist:
            formatted_messages.append({"role": msg.role, "content": msg.content})

        if image_data_urls and len(image_data_urls) > 0:
            for i in range(len(formatted_messages) - 1, -1, -1):
                if formatted_messages[i]["role"] == "user":
                    last_content = formatted_messages[i]["content"]
                    content_list = [{"type": "text", "text": last_content}]
                    for img_url in image_data_urls:
                        content_list.append(
                            {"type": "image_url", "image_url": {"url": img_url}}
                        )

                    formatted_messages[i]["content"] = content_list
                    break
        try:
            response = await self.client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                messages=formatted_messages,
                temperature=0.5,
                max_tokens=512,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"❌ [AI Generate Error]: {e}")
            return "عذراً، واجهت مشكلة تقنية في الخادم. يرجى المحاولة مرة أخرى لاحقاً."

    # =====================================================================
    # [ 4. محرك استخراج التخصصات (Specialty Extraction) ]
    # =====================================================================
    async def extract_specialty(self, description: str, suggested_part: str) -> dict:
        available_specialties = """
        - ميكانيكا (موتور، فتيس، دورة تبريد، رادياتير، فرامل، شكمان)
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
            response = await self.client.chat.completions.create(
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
            print(f"❌ [Specialty Extraction Error]: {e}")
            return {"specialty": "ميكانيكا", "sub_specialty": "موتور"}

    # =====================================================================
    # [ 5. محرك استخراج بيانات التذكير (Reminder Data Extraction) ]
    # =====================================================================
    async def extract_reminder_details(self, advice_text: str) -> dict:
        """
        قراءة نصيحة الصيانة التي ولدها الـ AI، واستخراج عنوان ووصف دقيق
        ليتم استخدامه في جدولة التذكيرات.
        """
        system_prompt = "You are a data extraction API. Output ONLY raw JSON format. No markdown."

        user_prompt = f"""
        قم بتحليل نصيحة الصيانة التالية:
        "{advice_text}"

        قم باستخراج بيانات التذكير في صيغة JSON فقط بالهيكل التالي:
        {{
            "title": "عنوان قصير للتذكير (مثل: تغيير زيت المحرك)",
            "description": "وصف مبسط للمهمة المطلوبة",
            "frequency": "مدى التكرار (مثال: كل 6 شهور، كل 10000 كم، مرة واحدة) أو null إذا لم يذكر",
            "suggested_date": "تاريخ مقترح بصيغة YYYY-MM-DD أو null إذا لم يذكر",
            "notification_time": "وقت التذكير المفضل أو null"
        }}
        """

        try:
            response = await self.client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=250,
            )

            result_text = response.choices[0].message.content
            clean_json_text = (
                result_text.replace("```json", "").replace("```", "").strip()
            )

            return json.loads(clean_json_text)

        except Exception as e:
            print(f"❌ [Reminder Extraction Error]: {e}")
            return {
                "title": "تذكير صيانة دورية",
                "description": "موعد الفحص والصيانة الدورية للسيارة",
            }

    # =====================================================================
    # [ 6. تحليل النوايا الذكي (Smart Intent Analysis) ]
    # =====================================================================
    async def analyze_intent(self, user_message: str) -> dict:
        system_prompt = "You are a specialized automotive intent classifier. Output ONLY raw JSON. No markdown."

        # 🔴 التعديل العام الذكي للطوارئ: التركيز على قدرة السيارة على الحركة بأمان
        user_prompt = f"""
                قم بتحليل رسالة المستخدم التالية المتعلقة بالسيارات لتحديد مسار الواجهة الأمامية (Frontend) بدقة قاطعة.
                رسالة المستخدم: "{user_message}"

                🚨 قاعدة السلامة القصوى (Safety-First Paradigm):
                أنت تقيم الأعطال بناءً على أسوأ سيناريو محتمل. أي خلل في الأنظمة الحيوية للسيارة (المحرك، الفرامل، نظام التوجيه) يرافقه أعراض مقلقة (أصوات غير طبيعية، حرارة، أدخنة، تسريب) يجب اعتباره "طوارئ" فوراً لمنع تدمر السيارة بالكامل أو تعريض السائق للخطر.

                قم بإرجاع JSON فقط يحتوي على الحقول المنطقية (true أو false) التالية:
                {{
                    "is_emergency": "true في حالات الخطر الداهم أو الأعطال الحرجة التي تتطلب إيقاف السيارة فوراً وعدم المخاطرة بتحريكها (وفقاً لقاعدة السلامة القصوى). اجعلها false فقط للأعطال البسيطة التي تسمح بقيادة السيارة إلى الورشة بأمان تام.",
                    "needs_mechanic": "true في أي حالة تتطلب فحص بورشة أو تدخل فني (سواء كانت طوارئ أو أعطال عادية). إذا كانت مجرد استشارة، اجعلها false.",
                    "is_advice": "true فقط إذا كان المستخدم يطلب نصيحة، مواعيد صيانة، أو يسأل عن أسعار/أنواع. وإلا false.",
                    "is_greeting": "true فقط إذا كانت الرسالة مجرد تحية أو تعارف. وإلا false."
                }}
                """

        try:
            response = await self.client.chat.completions.create(
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
            print(f"❌ [Local LLM Intent Error]: {e}")
            return {
                "is_emergency": False,
                "is_advice": False,
                "is_greeting": False,
                "needs_mechanic": False,
            }

    # =====================================================================
    # [ 7. محرك ترشيح قطع الغيار والروابط (Parts & Links Recommendation) ]
    # =====================================================================
    async def get_personalized_recommendations(
            self, car_info: str, description: str
    ) -> dict:
        system_prompt = (
            "You are a car parts expert API. Output ONLY raw JSON. No markdown."
        )

        user_prompt = f"""
        بناءً على سيارة {car_info}، رشح أهم قطعتي غيار لعلاج مشكلة: {description}.
        يجب أن تكون القطع مرتبطة تقنياً بالمشكلة.

        الرد JSON فقط بالهيكل التالي:
        {{
            "suggested_parts": ["اسم القطعة بالعربي 1", "اسم القطعة بالعربي 2"],
            "parts_en": ["Part Name 1 in English", "Part Name 2 in English"]
        }}
        """

        try:
            response = await self.client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
            )

            result_text = response.choices[0].message.content
            clean_json_text = (
                result_text.replace("```json", "").replace("```", "").strip()
            )
            ai_data = json.loads(clean_json_text)

            final_links = []
            parts_ar = ai_data.get("suggested_parts", [])
            parts_en = ai_data.get("parts_en", [])

            car_brand = car_info.split()[0] if car_info else ""

            for i in range(len(parts_en)):
                p_ar = parts_ar[i]
                p_en = parts_en[i]

                clean_query = f"{car_brand} {p_en}".strip()
                encoded_query = urllib.parse.quote_plus(clean_query)

                final_links.append(
                    {
                        "link_title": f"شراء {p_ar} من أمازون",
                        "url": f"https://www.amazon.eg/s?k={encoded_query}",
                    }
                )

                final_links.append(
                    {
                        "link_title": f"شراء {p_ar} من توفيقيه",
                        "url": f"https://tawfiqia.com/ar/catalogsearch/result/?q={encoded_query}",
                    }
                )

            return {"suggested_parts": parts_ar, "search_links": final_links}

        except Exception as e:
            print(f"❌ [Get Recommendations Error]: {e}")
            return {"suggested_parts": [], "search_links": []}

    # =====================================================================
    # [ 8. فحص المستندات (KYC Verification) ]
    # =====================================================================
    async def verify_document(
            self, image_data: str, doc_type: str = "رخصة ورشة سيارات"
    ) -> dict:
        """
        فحص المستندات باستخدام Vision AI مع إرجاع JSON نظيف.
        """
        try:
            if not image_data.startswith("data:image/"):
                return {
                    "is_approved": False,
                    "feedback": "تنسيق الصورة غير صالح. يجب أن يبدأ بـ 'data:image/...'",
                }

            prompt = (
                f"أنت خبير أمني مسؤول عن تدقيق المستندات (KYC). "
                f"قم بفحص هذه الصورة التي تمثل: {doc_type}. "
                "تأكد من أن الصورة واضحة، وأن المستند يبدو حقيقياً (غير معدل)، "
                "وأنه يطابق النوع المطلوب. "
                "قم بالرد باستخدام هيكل JSON التالي فقط: "
                '{"is_approved": boolean, "feedback": "string"}'
            )

            response = await self.client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_data}},
                        ],
                    }
                ],
                response_format={"type": "json_object"},
            )

            result_text = response.choices[0].message.content
            result = json.loads(result_text)
            print(f"🤖 Raw AI Response: {result_text}")

            return {
                "is_approved": bool(result.get("is_approved", False)),
                "feedback": str(
                    result.get("feedback", "لم يقدم الذكاء الاصطناعي سبباً واضحاً.")
                ),
            }

        except Exception as e:
            print(f"❌ AI Verification Error: {e}")
            return {
                "is_approved": False,
                "feedback": f"تعذر فحص المستند آلياً في الوقت الحالي. (التفاصيل: {str(e)})",
            }