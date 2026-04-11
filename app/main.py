import json
import base64
from typing import Optional

from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware

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
# [ إعدادات الـ CORS (Cross-Origin Resource Sharing) ]
# =====================================================================
# الهدف من هذا الجزء هو السماح لتطبيقات الواجهة الأمامية (Front-end) سواء ويب أو موبايل
# بالاتصال المباشر مع السيرفر دون أن يتم حظرها بواسطة حماية المتصفحات القياسية.

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # السماح باستقبال الطلبات من أي نطاق (Domain) أو جهاز
    allow_credentials=True, # السماح بمرور بيانات المصادقة مثل الـ (Tokens/Cookies)
    allow_methods=["*"], # السماح بجميع أنواع الطلبات (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"], # السماح بجميع الترويسات (Headers)، وهذا ضروري جداً لتخطي شاشة ngrok التحذيرية
)

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
def search_mechanics_in_db(
    query_keyword: Optional[str],
    min_rating: int,
    sort_by: str,
    user_lat: Optional[float],
    user_lng: Optional[float]
):
    """
    محرك البحث والفلترة الخاص بالفنيين.
    يدعم البحث بالاسم أو التخصص، والترتيب بالمسافة.
    (تم إيقاف فلتر التقييم مؤقتاً لحين إضافة عمود Rating في قاعدة البيانات)
    """
    conn = pymssql.connect(
        server=settings.DB_SERVER,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
    )
    cursor = conn.cursor(as_dict=True)

    # 1. الاستعلام الأساسي (تم إيقاف شرط التقييم مؤقتاً)
    sql = f"""
        SELECT DISTINCT
            u.Id AS MechanicId,
            u.FirstName + ' ' + u.LastName AS Name,
            u.Phone,
            -- mp.Rating, <-- TODO: Uncomment when Rating column is added
            0 AS Rating, -- قيمة مؤقتة (Dummy) عشان الفرونت إند ميضربش
            s.Name AS Specialty,
            mp.Location_Latitude AS Latitude,
            mp.Location_Longitude AS Longitude
        FROM dbo.Users u
        INNER JOIN dbo.MechanicProfile mp ON u.Id = mp.UserId
        INNER JOIN dbo.Specializations s ON mp.Id = s.MechanicProfileId
        LEFT JOIN dbo.SubSpecializations ss ON s.Id = ss.SpecializationId
        WHERE mp.IsAvailable = 1 
        -- AND mp.Rating >= {min_rating} <-- TODO: Uncomment when Rating is added
    """

    # 2. فلترة بكلمة البحث (لو اليوزر كتب حاجة)
    if query_keyword:
        sql += f"""
            AND (
                u.FirstName LIKE N'%{query_keyword}%' OR 
                u.LastName LIKE N'%{query_keyword}%' OR 
                s.Name LIKE N'%{query_keyword}%' OR 
                ss.Name LIKE N'%{query_keyword}%'
            )
        """

        # 3. الترتيب (Ranking)
        if sort_by == "distance" and user_lat and user_lng:
            # حساب المسافة التقريبية للترتيب (الأقرب يظهر الأول)
            sql += f" ORDER BY (POWER(mp.Location_Latitude - {user_lat}, 2) + POWER(mp.Location_Longitude - {user_lng}, 2)) ASC"
        else:
            # الترتيب الافتراضي مؤقتاً: الترتيب بالاسم المدمج عشان الـ DISTINCT متزعلش
            sql += " ORDER BY Name ASC"

    cursor.execute(sql)
    results = cursor.fetchall()
    conn.close()
    return results


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


@safe_db_call
def get_search_suggestions_from_db(query_keyword: str):
    """
    جلب اقتراحات البحث السريعة (أسماء فنيين أو تخصصات).
    تستخدم UNION لدمج النتائج من جداول مختلفة في قائمة واحدة سريعة.
    """
    # لو اليوزر كتب أقل من حرفين، مش هنروح للداتا بيز عشان نوفر موارد
    if not query_keyword or len(query_keyword) < 2:
        return []

    conn = pymssql.connect(
        server=settings.DB_SERVER,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
    )
    cursor = conn.cursor(as_dict=True)

    # بنسحب أفضل 7 اقتراحات بس عشان الـ UI ميبقاش زحمة
    sql = f"""
        SELECT DISTINCT TOP 7 Suggestion, Type FROM (
            -- البحث في أسماء الفنيين المتاحين
            SELECT (u.FirstName + ' ' + u.LastName) AS Suggestion, N'فني' AS Type 
            FROM dbo.Users u 
            INNER JOIN dbo.MechanicProfile mp ON u.Id = mp.UserId 
            WHERE mp.IsAvailable = 1 AND (u.FirstName LIKE N'%{query_keyword}%' OR u.LastName LIKE N'%{query_keyword}%')

            UNION

            -- البحث في التخصصات العامة
            SELECT Name AS Suggestion, N'تخصص' AS Type 
            FROM dbo.Specializations 
            WHERE Name LIKE N'%{query_keyword}%'

            UNION

            -- البحث في التخصصات الدقيقة
            SELECT Name AS Suggestion, N'تخصص دقيق' AS Type 
            FROM dbo.SubSpecializations 
            WHERE Name LIKE N'%{query_keyword}%'
        ) AS CombinedResults
    """
    cursor.execute(sql)
    results = cursor.fetchall()
    conn.close()
    return results


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

        # 3. تحليل النية بالذكاء الاصطناعي
        intent_data = await ai.analyze_intent(description)
        is_emergency = intent_data.get("is_emergency", False)
        is_advice = intent_data.get("is_advice", False)
        is_greeting = intent_data.get("is_greeting", False)
        needs_mechanic = intent_data.get("needs_mechanic", False)

        print(f"🧠 AI Intent Analysis: {intent_data}")

        # 4. البحث في RAG (لجلب بيانات العطل التقنية)
        search_results = db.search(description, n_results=1)
        metadata_list = search_results["metadatas"][0]
        top_case = metadata_list[0]
        difficulty = str(top_case.get("مستوى الصعوبة", "سهل")).strip()
        suggested_part = top_case.get("القطعة المرشحة", "غير محدد")
        suggested_solution = top_case.get("الحل المقترح", "يرجى الفحص")

        # 5. منطق التحية
        if is_greeting and not is_emergency and not needs_mechanic:
            instructions = "أنت GearUp AI، خبير سيارات ودود. رد بترحيب وذكر بتخصصك فقط."
            ai_chat_answer = await ai.generate_response(messages, [user_context, instructions], image_data_url)
            return RecommendationResponse(
                query=description, ai_answer=ai_chat_answer, source_documents=[], requires_feedback=False
            )

        # 6. جلب بيانات الفنيين بناءً على تحليل الـ AI
        unique_mechanics_list = []
        is_advice_mode = is_advice and not is_emergency

        user_asking_for_workshop = any(
            word in description.lower() for word in ["ورشة", "ميكانيكي", "فني", "تصليح", "مركز صيانة"]
        )

        is_hard_issue = (
            (difficulty == "صعب" or needs_mechanic or is_emergency or user_asking_for_workshop)
            and not is_advice_mode
        )

        # استخراج التخصص وجلب الفنيين
        if is_hard_issue:
            specialty_json = await ai.extract_specialty(description, suggested_part)
            mechanics_list = get_mechanics_from_db(
                specialty_json.get("specialty", "ميكانيكا"),
                specialty_json.get("sub_specialty", ""),
            )

            if mechanics_list:
                seen_ids = set()
                for m in mechanics_list:
                    m_id = m.get("MechanicId")
                    if m_id not in seen_ids:
                        unique_mechanics_list.append(m)
                        seen_ids.add(m_id)

        # 7. بناء الرد النهائي وتوجيه الـ AI
        offers_reminder_flag = False
        auto_fill_data = {"service_type": None, "required_service": None, "location": None, "gps": False}

        if is_advice_mode:
            # حالة 1: نصيحة عامة
            instructions = f"{user_context} قدم نصائح صيانة دورية وودية واعرض إنشاء تذكير. لا تذكر أي فنيين."
            offers_reminder_flag = True

        elif is_emergency:
            # حالة 2: طوارئ حقيقية 🔴
            auto_fill_data = {
                "service_type": "خدمة طارئة",
                "required_service": "إنقاذ وتطوير",
                "location": "ميكانيكي متنقل",
                "gps": True
            }
            instructions = (
                f"أنت خبير طوارئ سيارات. {user_context}. حافظ على نبرة هادئة ومطمئنة ('سلامتك أهم'). "
                f"الحل المقترح حالياً: {suggested_solution}. "
                f"قدم خطوات أمان فورية، ثم أخبر المستخدم بوضوح أن هناك فريق إنقاذ متاح الآن، "
                f"وانصحه بالضغط على زر 'حجز خدمة طارئة' للمتابعة فوراً. ممنوع ذكر أسماء فنيين."
            )

        elif is_hard_issue:
            # حالة 3: عطل محتاج ميكانيكي بس مش طوارئ 🟡
            auto_fill_data = {
                "service_type": "حجز ورشة",
                "required_service": "فحص وإصلاح",
                "location": "ورشة الفني",
                "gps": False
            }
            instructions = (
                f"أنت خبير سيارات. {user_context}. العطل يحتاج لتدخل فني ولكنه ليس حالة طوارئ خطيرة. "
                f"الحل المقترح: {suggested_solution}. "
                f"اشرح المشكلة ببساطة، وأخبر المستخدم أنه يمكنه حجز موعد مع فني متخصص الآن، "
                f"وانصحه بالضغط على زر 'حجز فني' الموجود أمامه. ممنوع إثارة الذعر."
            )

        else:
            # حالة 4: عطل بسيط ممكن اليوزر يعمله بنفسه 🟢
            instructions = f"{user_context} المشكلة بسيطة ويمكن حلها. الحل المقترح: {suggested_solution}. التنسيق: خطوات الحل."

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
            is_emergency=is_emergency,
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


# =====================================================================
# [ 5. مسارات محرك البحث - Search Engine ]
# =====================================================================

@app.get("/search/mechanics", response_model=dict)
async def search_mechanics_endpoint(
        q: Optional[str] = Query(None, description="كلمة البحث (اسم الفني، التخصص، أو وصف المشكلة)"),
        min_rating: int = Query(3, description="الحد الأدنى للتقييم (الافتراضي 3 نجوم)"),
        sort_by: str = Query("rating", description="ترتيب حسب: rating أو distance"),
        user_lat: Optional[float] = Query(None, description="خط عرض المستخدم"),
        user_lng: Optional[float] = Query(None, description="خط طول المستخدم")
):
    """
    البحث الشامل عن الفنيين (يدعم البحث الدلالي Semantic Search للأعطال)
    المتطلبات المغطاة: (FR-1, FR-2, FR-4, FR-6)
    """

    # 1. التحقق من صحة البيانات (Validation)
    if sort_by == "distance" and (user_lat is None or user_lng is None):
        raise HTTPException(
            status_code=400,
            detail="عذراً، يجب إرسال إحداثيات الموقع (GPS) عند اختيار الترتيب حسب المسافة."
        )

    search_keyword = q

    # 2. تحليل البحث باستخدام الذكاء الاصطناعي (Semantic Search)
    # لو المستخدم كتب وصف لعطل (أكثر من كلمة واحدة)، الـ AI بيستنتج التخصص
    if q and len(q.split()) > 1:
        try:
            specialty_json = await ai.extract_specialty(q, "")
            extracted_sub = specialty_json.get("sub_specialty", "").strip()
            extracted_spec = specialty_json.get("specialty", "").strip()

            # الأولوية للتخصص الدقيق، ثم العام
            ai_keyword = extracted_sub if extracted_sub else extracted_spec

            if ai_keyword and ai_keyword != "غير محدد":
                search_keyword = ai_keyword
                print(f"🤖 AI interpreted: '{q}' -> '{search_keyword}'")
        except Exception as e:
            print(f"⚠️ AI Search Error: {e}")

    # 3. جلب النتائج من قاعدة البيانات
    results = search_mechanics_in_db(search_keyword, min_rating, sort_by, user_lat, user_lng)

    if results is None:
        raise HTTPException(status_code=500, detail="خطأ في الوصول لقاعدة البيانات.")

    return {
        "status": "success",
        "result_count": len(results),
        "ai_interpreted_as": search_keyword if search_keyword != q else None,
        "data": results
    }


@app.get("/search/suggest")
async def suggest_endpoint(
        q: str = Query(..., description="الكلمة التي يكتبها المستخدم (حرفين فأكثر)")
):
    """ الاقتراحات التلقائية أثناء الكتابة (FR-3) """
    if len(q) < 2:
        return {"status": "success", "data": []}

    results = get_search_suggestions_from_db(q)

    if results is None:
        raise HTTPException(status_code=500, detail="خطأ في جلب الاقتراحات.")

    return {"status": "success", "data": results}


# =====================================================================
# [ 6. تفاصيل الفني - Detailed View (FR-5) ]
# =====================================================================

@app.get("/mechanic/{mechanic_id}")
async def get_mechanic_details(mechanic_id: str):
    """ جلب البيانات الكاملة للفني عند اختياره من النتائج (FR-5) """
    try:
        conn = pymssql.connect(
            server=settings.DB_SERVER,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME,
        )
        cursor = conn.cursor(as_dict=True)

        sql = f"""
            SELECT 
                u.Id, u.FirstName + ' ' + u.LastName AS FullName, u.Phone, u.Email,
                mp.Location_Latitude, mp.Location_Longitude, mp.YearsOfExperience,
                mp.Bio, 0 AS Rating, s.Name AS Specialty
            FROM dbo.Users u
            INNER JOIN dbo.MechanicProfile mp ON u.Id = mp.UserId
            LEFT JOIN dbo.Specializations s ON mp.Id = s.MechanicProfileId
            WHERE u.Id = '{mechanic_id}'
        """
        cursor.execute(sql)
        mechanic = cursor.fetchone()
        conn.close()

        if not mechanic:
            raise HTTPException(status_code=404, detail="الفني غير موجود.")

        return {"status": "success", "data": mechanic}

    except Exception as e:
        print(f"❌ Detail View Error: {e}")
        raise HTTPException(status_code=500, detail="حدث خطأ أثناء جلب التفاصيل.")