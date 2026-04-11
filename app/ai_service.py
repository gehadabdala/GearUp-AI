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
        # لستة التخصصات الكاملة بتاعتك
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

    # 3. محرك تحليل النية (Intent Classifier) - اللوجيك العبقري بتاعك
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
            print(f"❌ [Intent Analysis Error]: {e} - Falling back to local model...")
            try:
                local_prompt = f"System: {system_prompt}\nUser: {user_prompt}\nAssistant: "
                local_resp = simple_llm_service.generate(
                    prompt=local_prompt, max_tokens=200, temperature=0.0
                )
                clean_json = local_resp.replace("```json", "").replace("```", "").strip()
                return json.loads(clean_json)
            except Exception as local_e:
                print(f"❌ [Local LLM Intent Error]: {local_e}")
                # قيم احتياطية آمنة
                return {
                    "is_emergency": False,
                    "is_advice": False,
                    "is_greeting": False,
                    "needs_mechanic": False
                }

    # 4. محرك استخراج بيانات التذكير
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

        # 5. محرك التوصيات الشخصية (الإصدار المحصن)
        async def get_personalized_recommendations(
                self, user_car_model: str, problem_type: str
        ) -> dict:
            """
            بناءً على موديل العربية ونوع المشكلة، بنقترح قطع غيار بطريقة آمنة ومحصنة.
            """
            system_prompt = "You are a JSON API. You MUST return ONLY valid JSON. No markdown, no conversational text."
            user_prompt = f"""
            المستخدم لديه سيارة {user_car_model} ويشتكي من: {problem_type}.
            اقترح قطع الغيار التي قد يحتاجها لحل المشكلة، وقم بتوليد روابط بحث حقيقية لشرائها من Amazon Egypt.

            صيغة الـ JSON المطلوبة حرفياً:
            {{
                "suggested_parts": ["اسم القطعة 1", "اسم القطعة 2"],
                "search_links": [
                    {{"site": "Amazon Egypt", "url": "https://www.amazon.eg/s?k=اسم+القطعة"}}
                ]
            }}
            """

            try:
                # 1. المحاولة الأولى: الموديل الأساسي
                response = self.client.chat.completions.create(
                    model=self.DEFAULT_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.0,
                )
                raw_content = response.choices[0].message.content

                # التنظيف العنيف للـ JSON (Extract only the curly braces)
                import re
                json_match = re.search(r'\{.*\}', raw_content, re.DOTALL)
                clean_json = json_match.group(0) if json_match else raw_content

                return json.loads(clean_json)

            except Exception as e:
                print(f"❌ [AI Parts Error]: {e} - Falling back to local model...")
                try:
                    # 2. المحاولة التانية: الموديل المحلي لو النت فصل
                    local_prompt = f"System: {system_prompt}\nUser: {user_prompt}\nAssistant: "
                    local_resp = simple_llm_service.generate(prompt=local_prompt, max_tokens=300, temperature=0.0)

                    import re
                    json_match = re.search(r'\{.*\}', local_resp, re.DOTALL)
                    clean_json = json_match.group(0) if json_match else local_resp

                    return json.loads(clean_json)

                except Exception as local_e:
                    print(f"❌ [Local LLM Parts Error]: {local_e} - Using Manual Fallback")

                    # 3. المحاولة التالتة (قشة الغريق): استخراج يدوي عشان اللستة مترجعش فاضية أبداً
                    fallback_parts = []
                    if "مساح" in problem_type:
                        fallback_parts = ["مساحات زجاج", "ريش مساحات"]
                    elif "فرامل" in problem_type or "تزييق" in problem_type:
                        fallback_parts = ["تيل فرامل", "طنابير"]
                    elif "زيت" in problem_type:
                        fallback_parts = ["زيت محرك", "فلتر زيت"]
                    elif "تكييف" in problem_type or "سخونة" in problem_type:
                        fallback_parts = ["فلتر تكييف", "فريون"]
                    else:
                        fallback_parts = ["أدوات فحص السيارة"]

                    links = []
                    for p in fallback_parts:
                        links.append({
                            "site": "Amazon Egypt",
                            "url": f"https://www.amazon.eg/s?k={p.replace(' ', '+')}"
                        })

                    return {"suggested_parts": fallback_parts, "search_links": links}