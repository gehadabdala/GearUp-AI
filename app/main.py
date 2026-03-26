import json
import base64
from typing import Optional

from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
import pymssql
import functools
from app.config import settings
from app.approval_service import ApprovalService
from app.models import (
    Message,
    RecommendationResponse,
    QueryRequest,
    ApprovalRequest,
    ApprovalResponse,
)

app = FastAPI(title="GearUp Recommendation System")

# =====================================================================
# [ 1. تهيئة المتغيرات العالمية (Global Variables) ]
# =====================================================================
db = None  # مرجع لقاعدة بيانات الـ Vector (ChromaDB)
ai = None  # مرجع لخدمة الذكاء الاصطناعي (Gemini)
approval_service = ApprovalService()


def safe_db_call(func):
    """
    (Decorator) دالة حماية غلافية:
    الهدف منها إن لو حصل أي مشكلة أو فصل في الـ SQL Server،
    الكود مايضربش 500 Internal Error، وبدل كده يرجع None والـ AI يكمل شغله عادي.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(f"❌ Database Error in {func.__name__}: {e}")
            return None

    return wrapper


# =====================================================================
# [ 2. دوال التفاعل مع قاعدة البيانات (Database Helpers) ]
# =====================================================================
@safe_db_call
def get_mechanics_from_db(specialty: str, sub_specialty: str):
    """
    جلب أفضل 3 فنيين متاحين بناءً على التخصص.
    المنطق (Logic): يتم إعطاء أولوية (Rank 1) للمتخصص في العطل الدقيق (مثلاً فرامل)،
    ثم (Rank 2) للمتخصص العام (عفشة).
    """
    conn = pymssql.connect(
        server=settings.DB_SERVER,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
    )
    cursor = conn.cursor(as_dict=True)

    query = f"""
                SELECT DISTINCT TOP 3 
                    u.Id AS MechanicId,
                    u.FirstName + ' ' + u.LastName AS Name, 
                    u.Phone, 
                    mp.Location_Latitude AS Latitude,
                    mp.Location_Longitude AS Longitude,
                    -- نظام التقييم لترتيب الفنيين الأنسب أولاً
                    CASE 
                        WHEN ss.Name LIKE N'%{sub_specialty}%' THEN 1 
                        WHEN s.Name LIKE N'%{specialty}%' THEN 2    
                        ELSE 3 
                    END AS Rank
                FROM dbo.Users u
                INNER JOIN dbo.MechanicProfile mp ON u.Id = mp.UserId
                INNER JOIN dbo.Specializations s ON mp.Id = s.MechanicProfileId
                LEFT JOIN dbo.SubSpecializations ss ON s.Id = ss.SpecializationId
                WHERE 
                    mp.IsAvailable = 1 -- الفني متاح حالياً
                    AND (s.Name LIKE N'%{specialty}%' OR ss.Name LIKE N'%{sub_specialty}%')
                ORDER BY Rank 
            """
    cursor.execute(query)
    mechanics = cursor.fetchall()
    conn.close()
    return mechanics


@safe_db_call
def get_user_context_data(user_id: str, car_id: Optional[str] = None):
    """
    جلب بيانات المستخدم وسيارته لبناء "سياق شخصي" (Personalized Context) للـ AI.
    يساعد الـ AI على التحدث مع المستخدم باسمه وذكر موديل سيارته.
    """
    if not user_id:
        return None

    conn = pymssql.connect(
        server=settings.DB_SERVER,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
    )
    cursor = conn.cursor(as_dict=True)

    # لو الفرونت بعت car_id محدد، هنجيب بيانات العربية دي بالظبط
    if car_id:
        query = f"""
            SELECT u.FirstName, c.Brand, c.Model, c.Year 
            FROM dbo.Users u
            LEFT JOIN dbo.CustomerProfile cp ON u.Id = cp.UserId
            LEFT JOIN dbo.Car c ON cp.Id = c.CustomerProfileId
            WHERE u.Id = '{user_id}' AND c.Id = '{car_id}'
        """
    # لو مبعتش (كحالة احتياطية)، هنجيب أول عربية تقابلنا زي زمان
    else:
        query = f"""
            SELECT TOP 1 u.FirstName, c.Brand, c.Model, c.Year 
            FROM dbo.Users u
            LEFT JOIN dbo.CustomerProfile cp ON u.Id = cp.UserId
            LEFT JOIN dbo.Car c ON cp.Id = c.CustomerProfileId
            WHERE u.Id = '{user_id}'
        """

    cursor.execute(query)
    data = cursor.fetchone()
    conn.close()
    return data


# @safe_db_call
# def get_mechanic_schedule(mechanic_name: str):
#     """دالة لجلب المواعيد المتاحة لميكانيكي محدد بالاسم (محمية)"""
#     conn = pymssql.connect(
#         server=settings.DB_SERVER,
#         user=settings.DB_USER,
#         password=settings.DB_PASSWORD,
#         database=settings.DB_NAME,
#     )
#     cursor = conn.cursor(as_dict=True)
#
#     query = f"""
#         SELECT AvailableDate, StartTime, EndTime
#         FROM dbo.MechanicSchedules ms
#         INNER JOIN dbo.MechanicProfile mp ON ms.MechanicProfileId = mp.Id
#         INNER JOIN dbo.Users u ON mp.UserId = u.Id
#         WHERE (u.FirstName + ' ' + u.LastName) LIKE N'%{mechanic_name}%'
#         AND ms.IsBooked = 0
#     """
#     cursor.execute(query)
#     schedules = cursor.fetchall()
#     conn.close()
#     return schedules


# =====================================================================
# [ 3. أحداث بدء التشغيل (Startup Events) ]
# =====================================================================
@app.on_event("startup")
async def startup_event():
    """تهيئة الـ AI و الـ VectorDB عند تشغيل السيرفر وحقن البيانات (Ingestion)"""
    global db, ai
    from app.database import VectorDB
    from app.ai_service import AIService

    db = VectorDB()
    ai = AIService()

    # تحميل البيانات
    db.ingest_data()


# =====================================================================
# [ 4. المسار الرئيسي: محرك التوصيات والتشخيص الذكي (Recommendation Engine) ]
# =====================================================================
@app.post("/recommend", response_model=RecommendationResponse)
async def get_recommendation(
    query_data: str = Form(...),
    user_id: Optional[str] = Form(None),
    car_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    try:
        # 1. تجهيز البيانات والصورة
        data_dict = json.loads(query_data)
        messages = [Message(**m) for m in data_dict.get("messages", [])]
        description = messages[-1].content

        image_data_url = None
        if file:
            if file.content_type not in ["image/jpeg", "image/png"]:
                raise HTTPException(
                    status_code=400, detail="يُسمح فقط بصيغ JPG و PNG للمرفقات."
                )
            contents = await file.read()
            if len(contents) > 5 * 1024 * 1024:
                raise HTTPException(
                    status_code=400,
                    detail="حجم الصورة يتجاوز الحد المسموح (5 ميجابايت).",
                )
            encoded = base64.b64encode(contents).decode("utf-8")
            image_data_url = f"data:{file.content_type};base64,{encoded}"

        # 2. جلب سياق المستخدم
        user_data = get_user_context_data(user_id, car_id)
        user_context = ""
        if user_data:
            f_name = user_data.get("FirstName", "يا صديقي")
            car_brand = user_data.get("Brand", "")
            car_model = user_data.get("Model", "")
            car_year = user_data.get("Year", "")
            user_context = f"[معلومة سرية: اسم المستخدم {f_name}، سيارته {car_brand} {car_model} موديل {car_year}. استخدم صيغة المذكر/المؤنث الصح واذكر اسم سيارته بلطافة.]"

        # 3. الكلمات المفتاحية وتنظيف النص
        # بنشيل الهمزات والمسافات الزيادة عشان نضمن الـ Matching يلقط "أغير" و "امتى"
        clean_desc = description.lower().replace("أ", "ا").replace("إ", "ا").strip()

        car_keywords = [
            "صوت",
            "خبط",
            "رائحة",
            "دواسة",
            "فتيس",
            "موتور",
            "محرك",
            "فرامل",
            "عجلة",
            "كاوتش",
            "بنزين",
            "حرارة",
            "زيت",
            "قير",
            "عطل",
            "بوجيهات",
            "مارش",
            "بطارية",
            "مساحات",
            "ميكانيكي",
            "ورشة",
            "فني",
            "تصليح",
            "صيانة",
            "فلتر",
            "تغيير",
        ]
        greeting_keywords = [
            "مين",
            "عرفني",
            "أنت",
            "اهلا",
            "سلام",
            "وظيفتك",
            "صباح",
            "مساء",
        ]
        advice_keywords = [
            "اغير",
            "امتى",
            "متى",
            "موعد",
            "مواعيد",
            "نصيحه",
            "صيانه",
            "جدول",
            "كل قد ايه",
            "كل كام",
            "احافظ",
        ]

        is_car_related = any(word in clean_desc for word in car_keywords)
        is_greeting = any(word in clean_desc for word in greeting_keywords)
        is_asking_for_advice = any(word in clean_desc for word in advice_keywords)

        # 4. البحث في قاعدة البيانات (RAG)
        search_results = db.search(description, n_results=1)
        distances = search_results.get("distances", [[]])[0]
        is_far_match = not distances or distances[0] > 0.3

        # 5. منطق التحية والدردشة العامة
        if is_greeting or (not is_car_related and is_far_match):
            instructions = "أنت GearUp AI، خبير سيارات ودود. إذا كان المستخدم يطلب نصائح صيانة دورية، قدم له نصائح مبسطة وغير معقدة. وإذا كانت مجرد تحية، رد بلباقة وذكره بتخصصك."
            ai_chat_answer = await ai.generate_response(
                messages, [user_context, instructions], image_data_url
            )
            return RecommendationResponse(
                query=description,
                ai_answer=ai_chat_answer,
                source_documents=[],
                requires_feedback=False,
            )

        # 6. استخراج بيانات العطل والكلمات الحساسة
        metadata_list = search_results["metadatas"][0]
        top_case = metadata_list[0]
        difficulty = str(top_case.get("مستوى الصعوبة", "سهل")).strip()
        suggested_part = top_case.get("القطعة المرشحة", "غير محدد")
        suggested_solution = top_case.get("الحل المقترح", "يرجى الفحص")

        serious_words = [
            "فتيس",
            "موتور",
            "محرك",
            "ناقل حركة",
            "جير",
            "عمرة",
            "شاسيه",
            "بيستم",
            "كنترول",
            "حرارة",
            "فرامل",
            "دينامو",
            "مارش",
            "كهرباء",
            "ضفيرة",
        ]
        contains_serious_word = any(word in clean_desc for word in serious_words)
        user_asking_for_workshop = any(
            word in clean_desc
            for word in ["ورشة", "ميكانيكي", "فني", "مركز صيانة", "تصليح"]
        )

        # 7. جلب الميكانيكية (للمسار الطارئ فقط)
        mechanics_text = ""
        extracted_mechanics_list = []
        specialty_json = await ai.extract_specialty(description, suggested_part)
        mechanics_list = get_mechanics_from_db(
            specialty_json.get("specialty", "ميكانيكا"),
            specialty_json.get("sub_specialty", ""),
        )

        if mechanics_list:
            # extracted_mechanics_list = mechanics_list
            mechanics_text = "\n\nإليك الفنيين المتاحين حالياً في نظامنا:\n"
            unique_mechanics_list = []
            seen_mechanics_ids = set()
            for m in mechanics_list:
                m_id = m.get("MechanicId")
                if m_id not in seen_mechanics_ids:
                    unique_mechanics_list.append(m)

                    lat, lng = m.get("Latitude", 0), m.get("Longitude", 0)
                    map_link = (
                        f"http://googleusercontent.com/maps.google.com/?q={lat},{lng}"
                    )
                    mechanics_text += f"- المهندس: {m.get('Name')} | 📞: {m.get('Phone')} | 📍 اللوكيشن: {map_link}\n"
                    seen_mechanics_ids.add(m_id)

        # 8. بناء الرد النهائي وتحديد المسار (الأولوية للنصيحة)
        offers_reminder_flag = False
        is_hard_issue = False
        instructions = ""

        # متغيرات الملء التلقائي
        auto_fill_service_type, auto_fill_required_service, auto_fill_location_type = (
            None,
            None,
            None,
        )
        auto_fill_use_gps = False
        auto_fill_has_attachment = True if file else False

        # --- ترتيب الشروط (التكة اللي بتصلح الـ JSON) ---
        if is_asking_for_advice:
            # مسار النصائح - له الأولوية القصوى
            instructions = f"{user_context} المستخدم يطلب نصائح صيانة دورية أو استشارة. قدم نصائح مبسطة وودية. في النهاية، اعرض عليه إنشاء تذكير صيانة صراحةً. لا تذكر أي ميكانيكيين في هذا الرد."
            offers_reminder_flag = True
            is_hard_issue = False

        elif difficulty == "صعب" or contains_serious_word or user_asking_for_workshop:
            # مسار الطوارئ
            is_hard_issue = True
            offers_reminder_flag = False
            auto_fill_service_type = "خدمة طارئة"
            auto_fill_required_service = "تشخيص"
            auto_fill_location_type = "ميكانيكي متنقل"
            auto_fill_use_gps = True
            instructions = (
                f"أنت خبير طوارئ ودود في GearUp. {user_context}. "
                "1. حذر المستخدم فوراً لو الحالة خطيرة (مثل خبط الموتور) وانصحه بالتوقف فوراً. "
                # التعديل الذكي هنا:
                f"2. إذا كان هناك حل مقترح ({suggested_solution})، التزم به. "
                "أما إذا لم يتوفر حل محدد، فاشرح باختصار أن أصوات الخبط عادة ما تتعلق بميكانيكا المحرك الداخلية (مثل الزيت أو البساتم) "
                "وتتطلب فحصاً فيزيائياً دقيقاً. (تجنب تماماً ذكر البطارية أو الدينامو كسبب للخبط). "
                "3. أكد للمستخدم أن الفنيين المرشحين 'متنقلين' وسيقومون بفحص السيارة في موقعها الحالي. "
                f"4. اعرض قائمة الفنيين بأسلوب منظم: {mechanics_text}"
            )

        elif difficulty == "متوسط":
            instructions = f"{user_context} الحل: {suggested_solution}. التنسيق: ⚠️ ملاحظة هامة، ⚙️ إيه المشكلة والحل؟، 👨‍🔧 نصيحة الخبير."
        else:
            instructions = f"{user_context} الحل: {suggested_solution}. التنسيق: ✅ لا تقلق الموضوع بسيط، 🛠️ خطوات الحل."

        # 9. تنفيذ الذكاء الاصطناعي وتوليد التذكير
        ai_final_answer = await ai.generate_response(
            messages, [instructions], image_data_url
        )

        final_source_docs = []
        if top_case:
            # لو المشكلة مش خطيرة، ابعت المستندات عادي
            if not is_hard_issue:
                final_source_docs = [top_case]
            else:
                # لو خطيرة، اتأكد إن المستند اللي طالع مش "سهل" (زي فلتر هواء)
                # عشان ما يضربش الـ Logic مع التحذير القوي اللي الـ AI قاله
                if difficulty != "سهل":
                    final_source_docs = [top_case]
                else:
                    final_source_docs = []
                    # لو الـ RAG جاب حاجة سهلة في وقت كارثة، بنخفيها

        (
            reminder_title,
            reminder_desc,
            suggested_frequency,
            suggested_date,
            suggested_end_date,
            notification_time,
        ) = [None] * 6

        if offers_reminder_flag:
            reminder_data = await ai.extract_reminder_details(ai_final_answer)
            reminder_title = reminder_data.get("title", "تذكير صيانة دورية")
            reminder_desc = reminder_data.get("description", description)
            suggested_frequency = reminder_data.get("frequency", "مرة واحدة فقط")

            start_date_str = reminder_data.get("suggested_date")
            if not start_date_str:
                start_date_str = (datetime.now() + timedelta(days=7)).strftime(
                    "%Y/%m/%d"
                )
            suggested_date = start_date_str

            try:
                dt_start = datetime.strptime(
                    start_date_str.replace("/", "-"), "%Y-%m-%d"
                )
                suggested_end_date = (dt_start + timedelta(days=365)).strftime(
                    "%Y/%m/%d"
                )
            except:
                suggested_end_date = (datetime.now() + timedelta(days=372)).strftime(
                    "%Y/%m/%d"
                )

            notification_time = reminder_data.get("notification_time", "09:00 AM")

        return RecommendationResponse(
            query=description,
            ai_answer=ai_final_answer,
            source_documents=final_source_docs,
            requires_feedback=not is_hard_issue,
            requires_mechanic=is_hard_issue,
            offers_reminder=offers_reminder_flag,
            recommended_mechanics=unique_mechanics_list if is_hard_issue else [],
            car_id=car_id,
            issue_summary=description,
            service_type=auto_fill_service_type,
            required_service=auto_fill_required_service,
            service_location_type=auto_fill_location_type,
            use_current_location=auto_fill_use_gps,
            has_attachment=auto_fill_has_attachment,
            suggested_reminder_title=reminder_title,
            suggested_reminder_desc=reminder_desc,
            suggested_frequency=suggested_frequency,
            suggested_date=suggested_date,
            suggested_end_date=suggested_end_date,
            notification_time=notification_time,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================
# [ 5. مسار التحقق من المستندات (OCR & Document Verification) ]
# =====================================================================
@app.post("/approve-mechanic")
async def approve_mechanic(
    mechanic_id: str = Form(...),
    doc_type: str = Form(...),
    file: UploadFile = File(...),
):
    """
    دالة للتحقق من أوراق ومستندات الفنيين (مثل: البطاقة الشخصية، رخصة الورشة).
    تستقبل صورة المستند، وتحولها لصيغة Base64، ثم ترسلها لخدمة الـ AI (Gemini Vision).
    """
    contents = await file.read()
    encoded = base64.b64encode(contents).decode("utf-8")
    image_data_url = f"data:{file.content_type};base64,{encoded}"

    result = await approval_service.verify_document(
        doc_type=doc_type, image_data=image_data_url
    )
    return result


# =====================================================================
# [ 6. نظام تقييم الردود (Feedback System) ]
# =====================================================================
@app.post("/feedback")
async def submit_feedback(
    user_id: str = Form(...),
    query: str = Form(...),
    ai_response: str = Form(...),
    is_helpful: bool = Form(...),
):
    """دالة لتسجيل تقييم المستخدم لرد الـ AI مع الاحتفاظ بسجل كامل للمحادثة"""
    try:
        conn = pymssql.connect(
            server=settings.DB_SERVER,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME,
        )
        cursor = conn.cursor()

        # استعلام لإدخال التقييم كـ Log جديد دايماً (Insert Only)
        query_sql = """
            INSERT INTO dbo.AI_Feedback (UserId, UserQuery, AIResponse, IsHelpful, CreatedAt) 
            VALUES (%s, %s, %s, %s, GETDATE())
        """
        cursor.execute(query_sql, (user_id, query, ai_response, is_helpful))

        conn.commit()
        conn.close()

        if is_helpful:
            response_message = (
                "شكراً لتقييمك الإيجابي! رأيك يساعدنا على تطوير GearUp للأفضل. 🚀"
            )
        else:
            response_message = "نعتذر إن لم تكن الإجابة مفيدة بالقدر الكافي. نقدر لك هذا التقييم، وسنعمل جاهدين على التعلم منه وتحسين جودة ردودنا في المرات القادمة. 🛠️"

        return {"status": "success", "message": response_message}

    except Exception as e:
        print(f"❌ Feedback Error: {e}")
        # حتى لو التقييم فشل مش عايزين نضرب Error لليوزر، نعديها عادي
        return {
            "status": "error",
            "message": "عذراً، يبدو أن هناك عطلاً بسيطاً في النظام ⚙️! لم نتمكن من حفظ تقييمك الآن.",
        }
