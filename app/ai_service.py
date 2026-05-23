import json
import base64
from openai import AsyncOpenAI
from app.models import Message
from app.config import settings
from datetime import datetime, timedelta

# from app.local_llm import simple_llm_service
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

        # الـ Prompt المفصل والذكي بتاعك
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

        # # =====================================================================
        # # [ 3. محرك قراءة المستندات (Vision & OCR) ]
        # # =====================================================================

        # """
        # قراءة النصوص من الصور (مثل الرخص والبطاقات) باستخدام الذكاء الاصطناعي.
        # """
        # try:
        #     response = await self.client.chat.completions.create(
        #         model=self.DEFAULT_MODEL,
        #         messages=[
        #             {
        #                 "role": "user",
        #                 "content": [
        #                     {"type": "text", "text": prompt},
        #                     {"type": "image_url", "image_url": {"url": image_data_url}},
        #                 ],
        #             }
        #         ],
        #         temperature=0.1,  # نستخدم Temperature 0.1 لضمان الدقة العالية وعدم التأليف (Hallucination) في قراءة الأرقام
        #     )
        #     return response.choices[0].message.content
        # except Exception as e:
        #     print(f"[OCR Error]: {e}")
        #     return f"خطأ في قراءة الصورة: {str(e)}"

    # =====================================================================
    # [ 4. محرك استخراج البيانات المهيكلة (Structured Data Extraction) ]
    # =====================================================================
    async def extract_specialty(self, description: str, suggested_part: str) -> dict:
        # لستة التخصصات الكاملة بتاعتك
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
            # تنظيف الرد من أي علامات Markdown قد يضيفها الموديل بالغلط
            clean_json_text = (
                result_text.replace("```json", "").replace("```", "").strip()
            )

            return json.loads(clean_json_text)

        except Exception as e:
            print(f"❌ [Specialty Extraction Error]: {e}")
            # Fallback (قيمة احتياطية) في حالة فشل التحليل حتى لا يتوقف النظام
            return {"specialty": "ميكانيكا", "sub_specialty": "موتور"}

    # =====================================================================
    # [ 5. محرك استخراج بيانات التذكير (Reminder Data Extraction) ]
    # =====================================================================
    async def extract_reminder_details(self, advice_text: str) -> dict:
        """
        قراءة نصيحة الصيانة التي ولدها الـ AI، واستخراج عنوان ووصف دقيق
        ليتم استخدامه في جدولة التذكيرات (Scheduled Reminders).
        """
        # جلب التاريخ والوقت الحاليين ديناميكياً في كل ريكويست
        current_now = datetime.now()
        current_date_str = current_now.strftime("%Y-%m-%d")
        current_time_str = current_now.strftime("%H:%M")

        system_prompt = "You are a data extraction API. Output ONLY raw JSON format. No markdown formatting, no explanations."

        user_prompt = f"""
        بناءً على نصيحة الصيانة التالية، قم باستخراج تفاصيل التذكير المناسب لجدولته للمستخدم بشكل محدد ودوري.
        النصيحة: "{advice_text}"

        ⚠️ معلومات الوقت الحالي الحقيقية للنظام (استخدمها لحساب التواريخ القادمة بدقة):
        - تاريخ اليوم: {current_date_str}
        - الوقت الحالي: {current_time_str}

        قم بإرجاع JSON فقط بالهيكل التالي وبدون أي نصوص إضافية أو علامات markdown:
        {{
            "title": "عنوان قصير ومحدد للتذكير (مثل: تغيير زيت المحرك)",
            "description": "وصف مختصر جداً لما يجب فعله",
            "frequency": "تكرار التذكير (مرة واحدة، شهرياً، سنوياً، أو كل 5000 كم)",
            "suggested_date": "التاريخ المقترح لبدء التذكير بصيغة YYYY-MM-DD (احسبه بدقة بالتقدم في الأيام/الأسابيع بناءً على تاريخ اليوم الموضح أعلاه)",
            "notification_time": "وقت الإشعار المقترح والمناسب للمستخدم بصيغة HH:MM"
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

            result_text = response.choices[0].message.content
            clean_json_text = (
                result_text.replace("```json", "").replace("```", "").strip()
            )

            return json.loads(clean_json_text)

        except Exception as e:
            print(f"❌ [Reminder Extraction Error]: {e}")
            # fallback ديناميكي برضه في حالة الفشل الكارثي
            return {
                "title": "تذكير صيانة السيارة",
                "description": "موعد الصيانة الدورية المقترح",
                "frequency": "دوري",
                "suggested_date": (current_now + timedelta(days=7)).strftime(
                    "%Y-%m-%d"
                ),
                "notification_time": current_time_str,
            }

    # =====================================================================
    # [ 6. تحليل النوايا الذكي (Smart Intent Analysis) ]
    # =====================================================================
    async def analyze_intent(self, user_message: str) -> dict:
        system_prompt = "You are a strict specialized automotive intent classifier API. Output ONLY raw JSON. No markdown."

        user_prompt = f"""
        قم بتحليل رسالة المستخدم التالية المتعلقة بالسيارات لتحديد الحقول المنطقية (true أو false) بدقة قاطعة وبدون أي تفكير مرن.
        رسالة المستخدم: "{user_message}"

        ⚠️ قواعد التصنيف الصارمة (Strict Rules):
        1. "is_emergency": اجعلها true فوراً وبدون أي تردد إذا كانت الرسالة تحتوي على أي شكوى من أصوات خطيرة في المحرك أو أعطال كارثية (أمثلة قاطعة: خبط في الموتور، رزع في الموتور، المحرك بيخبط، سخونة المحرك، دخان من الكبوت، عطل الفرامل، تسريب بنزين). أي شكوى فيها كلمة 'خبط' أو 'صوت في الموتور' هي حالة طارئة قاتلة للمحرك (true). وإلا false.
        2. "needs_mechanic": اجعلها true في أي حالة تتطلب فحص بورشة أو تدخل فني (هذا يشمل جميع حالات الطوارئ السابقة، ويشمل أيضاً الأعطال غير الخطيرة مثل: تكييف لا يعمل، فتيس يعلق، صوت في العفشة، تغيير مساعدين). إذا كانت مجرد استشارة عامة أو تحية، اجعلها false.
        3. "is_advice": اجعلها true فقط إذا كان المستخدم يطلب نصيحة عامة، مواعيد صيانة دورية، أو يسأل عن أسعار/أنواع (مثل: متى أغير الزيت، أفضل نوع كاوتش). وإلا false.
        4. "is_greeting": اجعلها true إذا كانت الرسالة مجرد تحية (السلام عليكم) أو سؤال عام يستفسر عن منصة GearUp وماذا تقدم. وإلا false.

        قم بإرجاع JSON فقط بالهيكل التالي:
        {{
            "is_emergency": false,
            "needs_mechanic": false,
            "is_advice": false,
            "is_greeting": false
        }}
        """

        try:
            response = await self.client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,  # صفر تماماً عشان نمنع الموديل من الإبداع والتأليف
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
            # حماية يدوية (Fallback) صايعة لو الـ API هنج عشان السيرفر ميعكش:
            is_dangerous = any(
                kw in user_message
                for kw in ["خبط", "رزع", "سخون", "حرارة", "دخان", "فرامل"]
            )
            return {
                "is_emergency": True if is_dangerous else False,
                "needs_mechanic": True if is_dangerous else False,
                "is_advice": False,
                "is_greeting": False,
            }

    # =====================================================================
    # [ 7. محرك ترشيح قطع الغيار والروابط (Parts & Links Recommendation) ]
    # =====================================================================
    async def get_personalized_recommendations(
        self, car_info: str, description: str
    ) -> dict:
        import urllib.parse

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
                temperature=0.1,  # خفضنا الـ Temperature لزيادة الدقة
            )

            result_text = response.choices[0].message.content
            clean_json_text = (
                result_text.replace("```json", "").replace("```", "").strip()
            )
            ai_data = json.loads(clean_json_text)

            final_links = []
            parts_ar = ai_data.get("suggested_parts", [])
            parts_en = ai_data.get("parts_en", [])

            # تنظيف ماركة السيارة
            car_brand = car_info.split()[0] if car_info else ""

            for i in range(len(parts_en)):
                p_ar = parts_ar[i]
                p_en = parts_en[i]

                # تنظيف الكلمات من أي رموز غريبة عشان اللينك ميضربش
                clean_query = f"{car_brand} {p_en}".strip()

                import urllib.parse

                # quote_plus بتحول المسافة لـ + وده اللي توفيقية وأمازون بيحبوه جداً
                encoded_query = urllib.parse.quote_plus(clean_query)

                # رابط أمازون
                final_links.append(
                    {
                        "link_title": f"شراء {p_ar} من أمازون",
                        "url": f"https://www.amazon.eg/s?k={encoded_query}",
                    }
                )

                # رابط توفيقيه - باستخدام المسار اللي بيفتح صفحة البحث دايماً
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

    async def verify_document(
        self, image_data: str, doc_type: str = "رخصة ورشة سيارات"
    ) -> dict:
        """
        فحص المستندات باستخدام Gemini 2.0 Flash عبر OpenRouter مع إرجاع JSON نظيف.
        """
        try:
            # 1. التحقق من التنسيق وفصل الـ Base64 بأمان
            if not image_data.startswith("data:image/"):
                return {
                    "is_approved": False,
                    "feedback": "تنسيق الصورة غير صالح. يجب أن يبدأ بـ 'data:image/...'",
                }

            # 2. الـ Prompt (تم فصل الأقواس لمنع تعارض f-string)
            prompt = (
                f"أنت خبير أمني مسؤول عن تدقيق المستندات (KYC). "
                f"قم بفحص هذه الصورة التي تمثل: {doc_type}. "
                "تأكد من أن الصورة واضحة، وأن المستند يبدو حقيقياً (غير معدل)، "
                "وأنه يطابق النوع المطلوب. "
                "قم بالرد باستخدام هيكل JSON التالي فقط: "
                '{"is_approved": boolean, "feedback": "string"}'
            )

            # 3. إرسال الطلب لـ الموديل
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

            # 4. قراءة الرد وتحويله
            result_text = response.choices[0].message.content
            result = json.loads(result_text)
            print(f"🤖 Raw AI Response: {result_text}")

            # 5. التأكد من وجود المفاتيح المطلوبة عشان السيرفر ميضربش
            return {
                "is_approved": bool(result.get("is_approved", False)),
                "feedback": str(
                    result.get("feedback", "لم يقدم الذكاء الاصطناعي سبباً واضحاً.")
                ),
            }

        except Exception as e:
            print(f"❌ AI Verification Error: {e}")
            # إرجاع رد آمن جداً في حالة حدوث أي خطأ بدل ما الـ API يقع
            return {
                "is_approved": False,
                "feedback": f"تعذر فحص المستند آلياً في الوقت الحالي. (التفاصيل: {str(e)})",
            }
