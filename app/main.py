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
    استرجاع بيانات العميل والسيارة لبناء سياق محادثة مخصص (Personalized Context).
    يسمح للذكاء الاصطناعي بمناداة العميل باسمه وذكر موديل سيارته لرفع جودة التجربة.
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
# [ 4. المسار الرئيسي: Recommendation Engine ]
# =====================================================================
@app.post("/recommend", response_model=RecommendationResponse)
async def get_recommendation(
        query_data: str = Form(...),
        user_id: Optional[str] = Form(None),
        car_id: Optional[str] = Form(None),
        file: Optional[UploadFile] = File(None),
):
    """
        المسار الأساسي لتحليل شكوى المستخدم:
        يقوم بدمج البحث في المستندات (RAG) مع ذكاء Gemini لتحليل الأعطال،
        تحديد مدى خطورتها، واقتراح فنيين أو تذكيرات صيانة.
    """
    try:
        # 1. تجهيز البيانات والصورة
        data_dict = json.loads(query_data)
        messages = [Message(**m) for m in data_dict.get("messages", [])]
        description = messages[-1].content

        image_data_url = None
        if file:
            contents = await file.read()
            encoded = base64.b64encode(contents).decode("utf-8")
            image_data_url = f"data:{file.content_type};base64,{encoded}"

        # 2. جلب سياق المستخدم
        user_data = get_user_context_data(user_id, car_id)
        user_context = ""
        if user_data:
            f_name = user_data.get("FirstName", "يا صديقي")
            car_brand = user_data.get("Brand", "")
            user_context = f"[معلومة سرية: اسم المستخدم {f_name}، سيارته {car_brand}. استخدم صيغة المذكر/المؤنث الصح.]"

        # 3. الكلمات المفتاحية وتنظيف النص
        clean_desc = description.lower().replace("أ", "ا").replace("إ", "ا").strip()
        words_in_desc = clean_desc.split()

        serious_words = [
            "فتيس",
            "موتور",
            "محرك",
            "ناقل حركة",
            "جير",
            "فرامل",
            "زيت",
            "دخان",
            "صوت",
            "خبط",
            "شياط",
            "ريحة",
            "ريحه",
            "بيسرب",
            "تسريب",
            "بينقط",
            "تنقيط",
            "بيحدف",
            "تحدف",
            "تيل",
            "طنابير",
            "طنبور",
            "كاوتش",
            "عجلة",
            "انفجار",
            "دواسة",
            "بنزين",
            "حراره",
            "حرارة",
            "سخونية",
            "سخونيه",
            "بتدخن"
        ]

        # كلمات الخطر اللي بتكسر مود النصيحة (Safety First)
        critical_safety_words = ["فرامل", "مش بتوقف", "دواسة", "دواسه", "حرارة", "حراره", "دخان", "حريقة", "خبط موتور"]
        is_critical_danger = any(word in clean_desc for word in critical_safety_words)

        greeting_keywords = [
            "مين",
            "عرفني",
            "أنت",
            "اهلا",
            "سلام",
            "وظيفتك"
        ]

        advice_keywords = [
            "اغير",
            "امتى",
            "متى",
            "موعد",
            "صيانه",
            "صيانة",
            "كل قد ايه",
            "احافظ",
            "اهتم",
            "نصيحة",
            "نصايح",
            "تنصحني"
        ]

        contains_serious_word = any(word in words_in_desc for word in serious_words)
        is_greeting = any(word in words_in_desc for word in greeting_keywords)
        is_asking_for_advice = any(word in clean_desc for word in advice_keywords)

        # 4. البحث في RAG
        search_results = db.search(description, n_results=1)
        metadata_list = search_results["metadatas"][0]
        top_case = metadata_list[0]
        difficulty = str(top_case.get("مستوى الصعوبة", "سهل")).strip()
        suggested_part = top_case.get("القطعة المرشحة", "غير محدد")
        suggested_solution = top_case.get("الحل المقترح", "يرجى الفحص")

        # 5. منطق التحية
        if is_greeting and not contains_serious_word and not is_critical_danger:
            instructions = "أنت GearUp AI، خبير سيارات ودود. رد بترحيب وذكر بتخصصك فقط."
            ai_chat_answer = await ai.generate_response(messages, [user_context, instructions], image_data_url)
            return RecommendationResponse(
                query=description, ai_answer=ai_chat_answer, source_documents=[], requires_feedback=False
            )

        # 6. جلب الميكانيكية
        mechanics_text = ""
        unique_mechanics_list = []

        # الأولوية: لو فيه خطر حقيقي، بنلغي "مود النصيحة" عشان الميكانيكية يظهروا
        is_advice_mode = is_asking_for_advice and not is_critical_danger

        user_asking_for_workshop = any(
            word in clean_desc for word in ["ورشة", "ميكانيكي", "فني", "تصليح", "مركز صيانة"])

        is_hard_issue = (
                (difficulty == "صعب" or contains_serious_word or user_asking_for_workshop or is_critical_danger)
                and not is_advice_mode
        )

        # التعديل الجوهري: لا نلمس الداتا بيز إلا لو حالة طوارئ حقيقية
        if is_hard_issue:
            specialty_json = await ai.extract_specialty(description, suggested_part)
            mechanics_list = get_mechanics_from_db(
                specialty_json.get("specialty", "ميكانيكا"),
                specialty_json.get("sub_specialty", ""),
            )

            if mechanics_list:
                mechanics_text = "\n\nإليك الفنيين المتاحين حالياً في نظامنا:\n"
                seen_ids = set()
                for m in mechanics_list:
                    m_id = m.get("MechanicId")
                    if m_id not in seen_ids:
                        unique_mechanics_list.append(m)
                        lat, lng = m.get("Latitude", 0), m.get("Longitude", 0)
                        map_link = f"http://googleusercontent.com/maps.google.com/?q={lat},{lng}"
                        mechanics_text += f"- {m.get('Name')} | 📞: {m.get('Phone')} | 📍: {map_link}\n"
                        seen_ids.add(m_id)

        # 7. بناء الرد النهائي
        offers_reminder_flag = False
        auto_fill_data = {"service_type": None, "required_service": None, "location": None, "gps": False}

        if is_advice_mode:
            instructions = f"{user_context} قدم نصائح صيانة دورية وودية واعرض إنشاء تذكير. لا تذكر أي فنيين."
            offers_reminder_flag = True
        elif is_hard_issue:
            auto_fill_data = {"service_type": "خدمة طارئة", "required_service": "تشخيص", "location": "ميكانيكي متنقل",
                              "gps": True}
            instructions = f"أنت خبير طوارئ. {user_context}. حذر المستخدم فوراً لو الحالة خطيرة (مثل مشاكل الفرامل). الحل المقترح: {suggested_solution}. الفنيين: {mechanics_text}"
        else:
            instructions = f"{user_context} الحل بسيط: {suggested_solution}. التنسيق: خطوات الحل."

        ai_final_answer = await ai.generate_response(messages, [instructions], image_data_url)

        # 8. استخراج التذكير
        reminder_fields = [None] * 6
        if offers_reminder_flag:
            r_data = await ai.extract_reminder_details(ai_final_answer)
            reminder_fields = [
                r_data.get("title"), r_data.get("description"), r_data.get("frequency"),
                r_data.get("suggested_date"), None, r_data.get("notification_time")
            ]

        return RecommendationResponse(
            query=description,
            ai_answer=ai_final_answer,
            source_documents=[top_case] if not is_hard_issue else [],
            requires_feedback=is_advice_mode or offers_reminder_flag or (not is_hard_issue),
            requires_mechanic=is_hard_issue,
            is_advice_mode=is_advice_mode,
            offers_reminder=offers_reminder_flag,
            recommended_mechanics=unique_mechanics_list,
            car_id=car_id,
            issue_summary=description,
            service_type=auto_fill_data["service_type"],
            required_service=auto_fill_data["required_service"],
            service_location_type=auto_fill_data["location"],
            use_current_location=auto_fill_data["gps"],
            has_attachment=True if file else False,
            suggested_reminder_title=reminder_fields[0],
            suggested_reminder_desc=reminder_fields[1],
            suggested_frequency=reminder_fields[2],
            suggested_date=reminder_fields[3],
            notification_time=reminder_fields[5],
        )

    except Exception as e:
        print(f"❌ Error: {e}")
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