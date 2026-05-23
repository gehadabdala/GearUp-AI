from importlib.metadata import files
import json
import base64
import httpx
from typing import List, Optional
import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware

import pymssql
import functools

from sympy import re
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
    allow_origins=["*"],  # السماح باستقبال الطلبات من أي نطاق (Domain) أو جهاز
    allow_credentials=True,  # السماح بمرور بيانات المصادقة مثل الـ (Tokens/Cookies)
    allow_methods=["*"],  # السماح بجميع أنواع الطلبات (GET, POST, PUT, DELETE, etc.)
    allow_headers=[
        "*"
    ],  # السماح بجميع الترويسات (Headers)، وهذا ضروري جداً لتخطي شاشة ngrok التحذيرية
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
    جلب أفضل 15 فني متاحين بناءً على التخصص والتقييم.
    """
    # 1. تنظيف هندسي سليم: لو المتغير راجع None نحوله لنص فاضي
    safe_spec = specialty if specialty and str(specialty).lower() != "none" else ""
    safe_sub = (
        sub_specialty if sub_specialty and str(sub_specialty).lower() != "none" else ""
    )

    # لو مفيش أي تخصص مبعوت، رجع القائمة فاضية (تصرف منطقي سليم)
    if not safe_spec and not safe_sub:
        return []

    conn = pymssql.connect(
        server=settings.DB_SERVER,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        charset="utf8",
    )
    cursor = conn.cursor(as_dict=True)

    query = f"""
        SELECT TOP 15 
            u.Id AS UserId,  -- 🔴 السر كله هنا! رجعناها UserId عشان الـ main.py بتاعك يشوفها
            u.FirstName + ' ' + ISNULL(u.LastName, '') AS Name, 
            u.Phone, 
            mp.Location_Latitude AS Latitude, 
            mp.Location_Longitude AS Longitude,
            COALESCE(AVG(CAST(br.Stars AS FLOAT)), 0) AS AverageRating,
            CASE 
                WHEN ss.Name LIKE N'%{safe_sub}%' OR ss.Name LIKE N'%{safe_spec}%' THEN 1 
                WHEN s.Name LIKE N'%{safe_spec}%' THEN 2    
                ELSE 3 
            END AS Rank
        FROM dbo.Users u
        INNER JOIN dbo.MechanicProfile mp ON u.Id = mp.UserId
        LEFT JOIN dbo.Specializations s ON mp.Id = s.MechanicProfileId
        LEFT JOIN dbo.SubSpecializationsForMechanic ssm ON u.Id = ssm.MechanicId 
        LEFT JOIN dbo.SubSpecializations ss ON ssm.SubSpecializationId = ss.Id
        LEFT JOIN dbo.BookingRatings br ON u.Id = br.MechanicId
        WHERE mp.IsAvailable = 1 
        AND (s.Name LIKE N'%{safe_spec}%' OR ss.Name LIKE N'%{safe_spec}%' OR ss.Name LIKE N'%{safe_sub}%')
        GROUP BY 
            u.Id, u.FirstName, u.LastName, u.Phone, 
            mp.Location_Latitude, mp.Location_Longitude, 
            ss.Name, s.Name
        HAVING COALESCE(AVG(CAST(br.Stars AS FLOAT)), 0) >= 3 OR COALESCE(AVG(CAST(br.Stars AS FLOAT)), 0) = 0
        ORDER BY Rank, AverageRating DESC 
    """

    cursor.execute(query)
    mechanics = cursor.fetchall()
    conn.close()
    return mechanics


@safe_db_call
def get_user_context_data(user_id: str, car_id: Optional[str] = None):
    """
    استرجاع بيانات العميل والسيارة لبناء سياق محادثة مخصص (Personalized Context).
    """
    if not user_id:
        return None

    conn = pymssql.connect(
        server=settings.DB_SERVER,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        charset="utf8",
    )
    cursor = conn.cursor(as_dict=True)

    if car_id:
        query = f"""
            SELECT u.FirstName, c.Brand, c.Model, c.Year 
            FROM dbo.Users u
            LEFT JOIN dbo.CustomerProfile cp ON u.Id = cp.UserId
            LEFT JOIN dbo.Car c ON cp.Id = c.CustomerProfileId
            WHERE u.Id = '{user_id}' AND c.Id = '{car_id}'
        """
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


import re


@safe_db_call
def search_mechanics_in_db(
    query_keyword: Optional[str],
    category: Optional[str],
    min_rating: int,
    is_available: Optional[bool],
    sort_by: str,
    user_lat: Optional[float],
    user_lng: Optional[float],
):
    conn = pymssql.connect(
        server=settings.DB_SERVER,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
    )
    cursor = conn.cursor(as_dict=True)

    sql = f"""
        SELECT 
            u.Id AS MechanicId,
            u.FirstName + ' ' + u.LastName AS Name,
            u.Phone,
            s.Name AS Specialty,
            mp.Location_Latitude AS Latitude,
            mp.Location_Longitude AS Longitude,
            COALESCE(AVG(CAST(br.Stars AS FLOAT)), 0) AS Rating
        FROM dbo.Users u
        INNER JOIN dbo.MechanicProfile mp ON u.Id = mp.UserId
        INNER JOIN dbo.Specializations s ON mp.Id = s.MechanicProfileId
        LEFT JOIN dbo.SubSpecializations ss ON s.Id = ss.SpecializationId
        LEFT JOIN dbo.BookingRatings br ON u.Id = br.MechanicId
        WHERE 1=1
    """

    if is_available is True:
        sql += " AND mp.IsAvailable = 1 "
    elif is_available is False:
        sql += " AND mp.IsAvailable = 0 "

    if category:
        sql += f" AND s.Name LIKE N'%{category}%' "

    if query_keyword:
        processed_keyword = re.sub(r"[اأإآ]", "[اأإآ]", query_keyword)
        processed_keyword = re.sub(r"[هة]", "[هة]", processed_keyword)
        processed_keyword = re.sub(r"[يى]", "[يى]", processed_keyword)

        # حل مشكلة الاسم المدمج
        sql += f"""
            AND (
                (u.FirstName + ' ' + u.LastName) LIKE N'%{processed_keyword}%' OR 
                u.FirstName LIKE N'%{processed_keyword}%' OR 
                u.LastName LIKE N'%{processed_keyword}%' OR 
                s.Name LIKE N'%{processed_keyword}%' OR 
                ss.Name LIKE N'%{processed_keyword}%'
            )
        """

    sql += " GROUP BY u.Id, u.FirstName, u.LastName, u.Phone, s.Name, mp.Location_Latitude, mp.Location_Longitude, mp.IsAvailable "

    # حل مشكلة الميكانيكية الجداد اللي تقييمهم لسه صفر
    sql += f" HAVING COALESCE(AVG(CAST(br.Stars AS FLOAT)), 0) >= {min_rating} OR COUNT(br.Stars) = 0 "

    if sort_by == "distance" and user_lat and user_lng:
        sql += f" ORDER BY (POWER(mp.Location_Latitude - {user_lat}, 2) + POWER(mp.Location_Longitude - {user_lng}, 2)) ASC"
    else:
        sql += " ORDER BY Rating DESC"

    cursor.execute(sql)
    results = cursor.fetchall()
    conn.close()
    return results


@safe_db_call
def get_search_suggestions_from_db(q: str):
    """
    جلب اقتراحات البحث بناءً على أول حرفين أو أكثر مع تحديد النوع (اسم فني / تخصص).
    """
    conn = pymssql.connect(
        server=settings.DB_SERVER,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
    )
    cursor = conn.cursor(as_dict=True)

    # بنستخدم UNION عشان نجمع الأسماء والتخصصات وكل واحد ياخد الـ Type بتاعه
    query = f"""
        SELECT TOP 10 Suggestion, Type
        FROM (
            -- اقتراحات بأسماء الفنيين
            SELECT 
                u.FirstName + ' ' + u.LastName AS Suggestion, 
                N'اسم فني' AS Type
            FROM dbo.Users u
            INNER JOIN dbo.MechanicProfile mp ON u.Id = mp.UserId -- بنضمن إنه ميكانيكي كامل البيانات
            WHERE u.Role = 2 
            AND (u.FirstName LIKE N'%{q}%' OR u.LastName LIKE N'%{q}%')
            
            UNION
            
            -- اقتراحات بالتخصصات الدقيقة (Sub-Specialties)
            SELECT 
                ss.Name AS Suggestion, 
                N'تخصص دقيق' AS Type
            FROM dbo.SubSpecializations ss
            WHERE ss.Name LIKE N'%{q}%'
            
            UNION
            
            -- اقتراحات بالتخصصات العامة
            SELECT 
                s.Name AS Suggestion, 
                N'تخصص عام' AS Type
            FROM dbo.Specializations s
            WHERE s.Name LIKE N'%{q}%'
        ) AS CombinedSuggestions
        ORDER BY Type DESC, Suggestion ASC
    """

    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()

    # هنا هنرجع الـ list of dicts زي ما هي لأن cursor(as_dict=True) بيقوم بالواجب
    return results


@safe_db_call
def get_mechanic_document_path(mechanic_id: str):
    """
    بتروح لجدول MechanicDocuments وتسحب قيمة الـ FilePath
     بناءً على الـ MechanicProfileId
    """
    conn = pymssql.connect(
        server=settings.DB_SERVER,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
    )
    cursor = conn.cursor(as_dict=True)
    # بنجيب المسار الخاص بأحدث مستند أو المستند الخاص بالورشة
    query = f"""
        SELECT TOP 1 FilePath 
        FROM dbo.MechanicDocuments 
        WHERE MechanicProfileId = '{mechanic_id}'
        ORDER BY CreatedAt DESC
    """
    cursor.execute(query)
    result = cursor.fetchone()
    conn.close()
    return result["FilePath"] if result else None


@safe_db_call
def update_document_status(mechanic_id: str, is_approved: bool):
    """
    تحديث حالة المستند (مقبول أو مرفوض) في الداتابيز.
    """
    conn = pymssql.connect(
        server=settings.DB_SERVER,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
    )
    cursor = conn.cursor()
    status_text = "Approved" if is_approved else "Rejected"

    # تحديث عمود Status
    query = f"""
        UPDATE dbo.MechanicDocuments 
        SET Status = N'{status_text}', 
            UpdatedAt = CURRENT_TIMESTAMP
        WHERE MechanicProfileId = '{mechanic_id}'
    """
    cursor.execute(query)
    conn.commit()
    conn.close()


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
    # db.ingest_data()
    print("🚀 Server is Live! Starting background ingestion automatically...")
    asyncio.create_task(asyncio.to_thread(db.ingest_data))


# 🟢 ضيفنا الـ Endpoint ده عشان نكلمه يدوي بعد ما الموقع يبقى Live
@app.post("/run-ingest")
async def trigger_ingestion():
    if db is None:
        return {"status": "error", "message": "Database not initialized"}

    # asyncio.to_thread بيشغل العملية الطويلة دي في الخلفية عشان الموقع يفضل سريع
    asyncio.create_task(asyncio.to_thread(db.ingest_data))
    return {
        "status": "success",
        "message": "جاري سحب البيانات في الخلفية. يمكنك استخدام الموقع الآن!",
    }


# =====================================================================
# [ 4. المسار الرئيسي: Recommendation Engine ]
# =====================================================================
@app.post("/recommend", response_model=RecommendationResponse)
async def get_recommendation(
    query_data: str = Form(...),
    user_id: Optional[str] = Form(None),
    car_id: Optional[str] = Form(None),
    file1: Optional[UploadFile] = File(None),  # الصورة الأولى (اختيارية)
    file2: Optional[UploadFile] = File(None),  # الصورة التانية (اختيارية)
    file3: Optional[UploadFile] = File(None),
):
    try:
        # 1. تجهيز البيانات والصورة
        data_dict = json.loads(query_data)
        messages = [Message(**m) for m in data_dict.get("messages", [])]
        description = messages[-1].content

        image_data_urls = []
        files = [f for f in [file1, file2, file3] if f is not None]
        if files:
            for file in files:

                contents = await file.read()

                encoded = base64.b64encode(contents).decode("utf-8")

                image_data_urls.append(f"data:{file.content_type};base64,{encoded}")
        # 2. جلب سياق المستخدم
        user_data = get_user_context_data(user_id, car_id)
        user_context = ""
        car_info = "سيارة"
        if user_data:
            f_name = user_data.get("FirstName", "يا صديقي")
            car_brand = user_data.get("Brand", "")
            car_info = car_brand if car_brand else "سيارة"
            user_context = f"[معلومة سرية: اسم المستخدم {f_name}، سيارته {car_brand}. استخدم صيغة المذكر/المؤنث الصح.]"

        # 3. تحليل النية بالذكاء الاصطناعي (مع حماية صارمة للأنواع المنطقية)
        intent_data = await ai.analyze_intent(description)

        # تحويل أي ناتج (سواء String أو Bool) لقيمة منطقية حقيقية
        is_emergency = str(intent_data.get("is_emergency", False)).lower() == "true"
        is_advice = str(intent_data.get("is_advice", False)).lower() == "true"
        is_greeting = str(intent_data.get("is_greeting", False)).lower() == "true"
        needs_mechanic = str(intent_data.get("needs_mechanic", False)).lower() == "true"

        print(
            f"🧠 AI Intent Analysis: Emergency={is_emergency}, Advice={is_advice}, Mechanic={needs_mechanic}"
        )

        # 4. البحث في RAG
        user_asking_for_workshop = any(
            word in description.lower()
            for word in [
                "ورشة",
                "ميكانيكي",
                "فني",
                "تصليح",
                "مركز صيانة",
                "احجز",
                "حجز",
            ]
        )
        is_advice_mode = (
            is_advice and not is_emergency
        ) and not user_asking_for_workshop
        if user_asking_for_workshop and not any(
            word in description for word in ["رجة", "صوت", "مشكلة", "عطل"]
        ):
            top_case = {}
            suggested_solution = "يرجى التوجه للفني للفحص"
            difficulty = "متوسط"
            suggested_part = "غير محدد"
        else:
            search_results = db.search(description, n_results=1)
            metadata_list = search_results["metadatas"][0]
            top_case = metadata_list[0]

            difficulty = str(
                top_case.get("مستوى الصعوبة", top_case.get("difficulty", "سهل"))
            ).strip()
            suggested_solution = top_case.get(
                "الحل المقترح", top_case.get("solution", "يرجى الفحص")
            )
            suggested_part = top_case.get(
                "القطعة المرشحة", top_case.get("parts", "غير محدد")
            )

        # 5. منطق التحية
        if is_greeting and not is_emergency and not needs_mechanic:
            instructions = (
                f"أنت GearUp AI، مساعد ذكي وخبير سيارات ودود. {user_context}. "
                "المستخدم يلقي التحية أو يسأل عن الموقع/المنصة. "
                "رد بترحيب حار وودود جداً، وعرّفه بمنصة GearUp وخدماتها بشكل عام وجذاب (مثل: حجز صيانة، فحص أعطال بالذكاء الاصطناعي، تذكيرات صيانة). "
                "⚠️ تحذير: ممنوع تماماً اقتراح قطع غيار، وممنوع توجيهه لحجز موعد طوارئ أو صيانة ميكانيكية حالياً، فقط تعارف وترحيب."
            )
            ai_chat_answer = await ai.generate_response(
                messages, [user_context, instructions], image_data_urls
            )
            return RecommendationResponse(
                query=description,
                ai_answer=ai_chat_answer,
                source_documents=[],
                requires_feedback=False,
                requires_mechanic=False,
                is_emergency=False,
                is_advice_mode=False,
                offers_reminder=False,
                recommended_mechanics=[],
                car_id=car_id,
                issue_summary=description,
                service_type=None,
                required_service=None,
                service_location_type=None,
                use_current_location=False,
                has_attachment=True if files and len(files) > 0 else False,
                recommended_spare_parts=[],
                external_links=[],
                car_brand=car_info if car_info != "سيارة" else None,
            )

        # 6. جلب ترشيحات قطع الغيار الذكية (باستخدام الـ AI)
        spare_parts_recommendations = []
        external_search_links = []

        # بنفحص: هل اليوزر داخل يطلب ميكانيكي/حجز مباشرة بدون ما يشرح عطل؟
        is_direct_booking_request = user_asking_for_workshop and not any(
            word in description
            for word in ["رجة", "صوت", "مشكلة", "عطل", "بايظة", "بتعمل"]
        )

        if not is_greeting and not is_direct_booking_request:
            try:
                parts_data = await ai.get_personalized_recommendations(
                    car_info, description
                )

                # تخزين القطع
                spare_parts_recommendations = parts_data.get("suggested_parts", [])
                # if not spare_parts_recommendations:
                #     # لو الموديل سماها اسم تاني زي spare_parts أو parts
                #     spare_parts_recommendations = parts_data.get(
                #         "spare_parts", parts_data.get("parts", [])
                #     )

                # تخزين اللينكات
                # تخزين اللينكات (صح وشغال بدون تكرار)
                raw_links = parts_data.get("search_links", [])
                if isinstance(raw_links, list):
                    for item in raw_links:
                        external_search_links.append(
                            {
                                "link_title": item.get("link_title"),
                                "url": item.get("url"),
                            }
                        )
            except Exception as e:
                print(f"⚠️ Error fetching personalized parts: {e}")

        # 7. جلب بيانات الفنيين
        mechanic_ids_list = []

        is_hard_issue = (
            difficulty == "صعب"
            or needs_mechanic
            or is_emergency
            or user_asking_for_workshop
        ) and not is_advice_mode

        if is_hard_issue:
            specialty_json = await ai.extract_specialty(description, suggested_part)
            mechanics_list = get_mechanics_from_db(
                specialty_json.get("specialty", "ميكانيكا"),
                specialty_json.get("sub_specialty", ""),
            )
            if mechanics_list:
                seen_ids = set()
                for m in mechanics_list:
                    # 🔴 التعديل هنا: بنقرأ الـ UserId
                    m_id = m.get("UserId") or m.get("userid")

                    if m_id and str(m_id).lower() != "none":
                        if m_id not in seen_ids:
                            mechanic_ids_list.append(str(m_id))
                            seen_ids.add(m_id)

        # 8. بناء الرد النهائي وتوجيه الـ AI
        offers_reminder_flag = False
        auto_fill_data = {
            "service_type": None,
            "required_service": None,
            "location": None,
            "gps": False,
        }

        # تلميح للـ AI عشان ينطق بقطع الغيار
        parts_hint = ""
        if spare_parts_recommendations:
            parts_hint = f"\nقم باقتراح قطع الغيار التالية للمستخدم بأسلوب جذاب: {', '.join(spare_parts_recommendations)}."

        if is_advice_mode:
            instructions = f"{user_context} قدم نصائح صيانة دورية وودية واعرض إنشاء تذكير. {parts_hint} لا تذكر أي فنيين."
            offers_reminder_flag = True

        elif is_emergency:
            auto_fill_data = {
                "service_type": "خدمة طارئة",
                "required_service": "إنقاذ وقطر",
                "location": "ميكانيكي متنقل",
                "gps": True,
            }
            instructions = (
                f"أنت خبير طوارئ سيارات. {user_context}. حافظ على نبرة هادئة ومطمئنة ('سلامتك أهم من أي شيء'). "
                f"قدم فقط إجراءات الأمان الفورية (مثل: التوقف على يمين الطريق، إطفاء المحرك). {parts_hint}"
                f"⚠️ تحذير صارم: ممنوع منعاً باتاً أن تطلب من المستخدم القيام بأي خطوات فحص. "
                f"بعد إجراءات الأمان، وجهه مباشرة للضغط على زر 'حجز خدمة طارئة'. لا تذكر أسماء فنيين."
            )

        elif is_hard_issue:
            # 🟡 مسار الحجز العادي (Standard Booking) - متوافق مع شاشة الـ UI

            # بنجيب التخصص الدقيق عشان نملى بيه حقل "نوع الخدمة"
            service_to_fill = "فحص شامل"
            if "specialty_json" in locals() and specialty_json:
                # 1. بنحاول ناخد التخصص الفرعي الأول (عشان يكون دقيق جداً)
                service_to_fill = specialty_json.get("sub_specialty")

                # 2. لو مفيش تخصص فرعي أو راجع بكلمة "غير محدد"، بناخد التخصص الأساسي
                if not service_to_fill or service_to_fill == "غير محدد":
                    service_to_fill = specialty_json.get("specialty", "فحص شامل")

            auto_fill_data = {
                "service_type": "حجز موعد",  # الكلمة اللي الفرونت هيعرف منها يفتح شاشة الـ Booking
                "required_service": service_to_fill,  # هنا هيتملى بالتخصص الفرعي أو الأساسي
                "location": "في الورشة",
                "gps": False,
            }

            if is_direct_booking_request:
                # 1. الرد الجديد (مباشر ومختصر لطلب الحجز)
                instructions = (
                    f"أنت مساعد GearUp الودود. {user_context}. "
                    f"المستخدم يريد حجز موعد مع ميكانيكي متخصص في {service_to_fill}. "
                    f"قم بالترحيب به بذكاء، وأكد له أنك رشحت له أفضل الفنيين المتاحين في القائمة أدناه. "
                    f"وجهه بوضوح للضغط على زر 'إضافة حجز جديد' واختيار الموعد المناسب. "
                    f"ممنوع تقديم أي تشخيصات تقنية أو احتمالات أعطال لأن المستخدم لم يطلب فحصاً بل طلب حجزاً."
                )
            else:
                vision_instruction = (
                    "\n- إذا كانت الصور المرفقة غير واضحة لتحديد العطل بدقة، اطلب من المستخدم بلطف تصوير العطل "
                    "من زاوية أقرب أو في إضاءة أفضل، مع تقديم تشخيص مبدئي بناءً على ما هو متاح."
                )
                # 2- (التشخيص المفصل للأعطال الصعبة)
                instructions = (
                    f"أنت خبير سيارات. {user_context}. العطل يحتاج لتدخل فني ولكنه ليس حالة طوارئ خطيرة. "
                    f"الحل المقترح: {suggested_solution}. {parts_hint} "
                    f"اشرح المشكلة ببساطة، ووجه المستخدم بوضوح للضغط على زر 'إضافة حجز جديد' "
                    f"لاختيار موعد وتاريخ مناسبين لزيارة الورشة. ممنوع إثارة الذعر."
                )

        else:
            instructions = f"{user_context} المشكلة بسيطة ويمكن حلها. الحل المقترح: {suggested_solution}. {parts_hint} التنسيق: خطوات الحل."

        ai_final_answer = await ai.generate_response(
            messages, [instructions], image_data_urls
        )
        # 9. استخراج التذكير وتجهيزه للفرونت إند (حسابات ديناميكية للتاريخ والوقت)
        reminder_fields = [None] * 6
        if offers_reminder_flag:
            try:
                r_data = await ai.extract_reminder_details(ai_final_answer)

                # حساب تاريخ احتياطي ديناميكي (كمان أسبوع من النهاردة) لو الموديل مطلعش داتا
                default_future_date = (datetime.now() + timedelta(days=7)).strftime(
                    "%Y-%m-%d"
                )
                default_time = datetime.now().strftime("%H:%M")

                reminder_fields = [
                    r_data.get("title", "تذكير صيانة دورية"),
                    r_data.get("description", "موعد الفحص والصيانة الدورية للسيارة"),
                    r_data.get("frequency", "دوري"),
                    r_data.get("suggested_date", default_future_date),
                    None,  # suggested_end_date
                    r_data.get("notification_time", default_time),
                ]
            except Exception as re:
                print(f"⚠️ Error in extracting reminder details: {re}")

        # 10. إرجاع النتيجة
        return RecommendationResponse(
            query=description,
            ai_answer=ai_final_answer,
            source_documents=[top_case] if not is_hard_issue else [],
            requires_feedback=is_advice_mode
            or offers_reminder_flag
            or (not is_hard_issue),
            requires_mechanic=is_hard_issue,
            is_emergency=is_emergency,
            is_advice_mode=is_advice_mode,
            offers_reminder=offers_reminder_flag,
            recommended_mechanics=mechanic_ids_list,
            car_id=car_id,
            issue_summary=description,
            service_type=auto_fill_data["service_type"],
            required_service=auto_fill_data["required_service"],
            service_location_type=auto_fill_data["location"],
            use_current_location=auto_fill_data["gps"],
            has_attachment=True if files and len(files) > 0 else False,
            suggested_reminder_title=reminder_fields[0],
            suggested_reminder_desc=reminder_fields[1],
            suggested_frequency=reminder_fields[2],
            suggested_date=reminder_fields[3],
            notification_time=reminder_fields[5],
            recommended_spare_parts=spare_parts_recommendations,
            external_links=external_search_links,
            car_brand=car_info if car_info != "سيارة" else None,
        )

    except Exception as e:
        print(f"❌ Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================
# [ 5. مسار التحقق من المستندات (OCR & Document Verification) ]
# =====================================================================
from fastapi import APIRouter, Form, File, UploadFile, HTTPException
import base64
import json


@app.post("/approve-mechanic")
async def approve_mechanic(
    mechanic_id: str = Form(...),
    document_url: Optional[str] = Form(None),  # Priority 1
):
    """
    التحقق الآلي من مستندات الفنيين باستخدام الـ Fallback النظيف.
    متوافق تماماً مع متغيراتك ومؤمن ضد نصوص Swagger الفارغة.
    """
    try:
        # 1. تحديد الرابط (الأولوية لـ document_url إذا كان يحتوي على رابط حقيقي)
        image_url = document_url
        if image_url:
            clean_url = image_url.strip().lower()
            if clean_url == "" or clean_url == "none":
                image_url = None

        # (Fallback -> الذهاب للداتا بيز لو مفيش URL مبعوت في الـ Form)
        if not image_url:
            image_url = get_mechanic_document_path(mechanic_id)

        if not image_url:
            raise HTTPException(
                status_code=404,
                detail="لم يتم العثور على مسار المستند في قاعدة البيانات أو الطلب.",
            )

        # 2. تحميل الصورة باستخدام httpx
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(image_url, headers=headers, follow_redirects=True)
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"فشل تحميل الصورة من السيرفر. الـ Status Code: {resp.status_code}",
                )

            contents = resp.content
            encoded = base64.b64encode(contents).decode("utf-8")
            # بنأمن التنسيق بـ image/jpeg عشان يطابق شرط الـ startswith في الـ ai_service
            image_data_url = f"data:image/jpeg;base64,{encoded}"

        # 3. إرسال الصورة للـ AI للتحليل بنفس المتغيرات الأصلية بتاعتك
        ai_result = await ai.verify_document(image_data=image_data_url)

        is_approved = ai_result.get("is_approved", False)
        ai_feedback = ai_result.get("feedback", "لم يتم تقديم تفاصيل.")

        # 4. تحديث جدول MechanicDocuments بالحالة الجديدة
        update_document_status(mechanic_id=mechanic_id, is_approved=is_approved)

        # 5. إرجاع النتيجة للـ Frontend بنفس الـ Structure المستقر بتاعك
        return {
            "status": "success",
            "mechanic_id": mechanic_id,
            "is_approved": is_approved,
            "ai_feedback": ai_feedback,
            "message": (
                "تم التحقق من المستند بنجاح." if is_approved else "تم رفض المستند."
            ),
        }

    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        print(f"❌ Document Verification Error: {e}")
        raise HTTPException(
            status_code=500, detail=f"حدث خطأ أثناء فحص المستند: {str(e)}"
        )


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
# [ 7. مسارات محرك البحث - Search Engine ]
# =====================================================================


# إعداد الراوتر
router = APIRouter()


@app.get("/search/mechanics", response_model=dict)
async def search_mechanics_endpoint(
    q: Optional[str] = Query(None, description="وصف المشكلة أو اسم الفني"),
    category: Optional[str] = Query(None, description="الفئة (ميكانيكا، كهرباء، إلخ)"),
    min_rating: float = Query(
        3.0, description="الحد الأدنى للتقييم (الافتراضي 3 نجوم)"
    ),
    is_available: Optional[bool] = Query(None, description="حالة التوافر الحالية"),
    sort_by: str = Query("rating", description="الترتيب حسب: rating أو distance"),
    user_lat: Optional[float] = Query(None, description="خط العرض للمستخدم"),
    user_lng: Optional[float] = Query(None, description="خط الطول للمستخدم"),
):
    """
    تنفيذ متطلبات البحث الذكي (FR-1, FR-2, FR-3, FR-6) من الـ PDF
    """

    if sort_by == "distance" and (user_lat is None or user_lng is None):
        raise HTTPException(
            status_code=400,
            detail="يجب إرسال إحداثيات الموقع (GPS) للترتيب حسب المسافة.",
        )

    search_keyword = q
    ai_interpreted = "Same as query"

    try:
        # 1. البحث الصارم في الداتا بيز (بيطبق اللوجيك بتاعك زي ما هو بالظبط)
        results = search_mechanics_in_db(
            query_keyword=search_keyword,
            category=category,
            min_rating=int(min_rating),
            is_available=is_available,
            sort_by=sort_by,
            user_lat=user_lat,
            user_lng=user_lng,
        )

        # 2. اللجام بتاع الـ AI: مش هنسأله إلا لو متأكدين إنه وصف عطل مش اسم شخص
        if not results and q:
            clean_q = q.replace('"', "").replace("'", "").strip()

            # كلمات مفتاحية بتعرفنا إن اليوزر بيوصف مشكلة مش بيبحث عن اسم شخص
            problem_keywords = [
                "صوت",
                "رجة",
                "بتعمل",
                "بايظ",
                "مشكلة",
                "عطل",
                "تيل",
                "فرامل",
                "موتور",
                "عفشة",
                "حرارة",
                "عربيتي",
                "سيارة",
                "دخان",
                "نور",
                "كهربا",
                "بتسخن",
                "خبط",
                "تسريب",
                "زيت",
                "ميه",
                "طرمبة",
                "كاوتش",
                "تكييف",
                "سمكرة",
                "بطارية",
                "سير",
                "بوجيهات",
                "ميكانيكا",
                "كهربائي",
            ]

            # هنعتبره وصف عطل لو: فيه كلمة من الكلمات اللي فوق، أو الجملة أطول من كلمتين (لأن الأسماء غالباً كلمتين)
            is_problem_desc = (
                any(kw in clean_q for kw in problem_keywords)
                or len(clean_q.split()) > 2
            )

            if is_problem_desc:
                # هنا بس هنسمح للـ AI يتدخل
                common_issues = ["فرامل", "بطارية", "كاوتش", "تكييف", "عفشة", "سمكرة"]
                found_issue = next(
                    (issue for issue in common_issues if issue in clean_q), None
                )

                if found_issue:
                    search_keyword = found_issue
                    print(f"✅ Manual Override: Found '{found_issue}' in query.")
                else:
                    specialty_json = await ai.extract_specialty(clean_q, "")
                    # حل إيرور الـ NoneType اللي صلحناه من شوية
                    extracted_sub = (specialty_json.get("sub_specialty") or "").strip()
                    extracted_spec = (specialty_json.get("specialty") or "").strip()

                    if extracted_sub and extracted_sub != "غير محدد":
                        search_keyword = extracted_sub
                    elif extracted_spec and extracted_spec != "غير محدد":
                        search_keyword = extracted_spec

                # لو الـ AI جاب تخصص، نعمل سيرش تاني بيه
                if search_keyword != q and search_keyword != "":
                    print(f"🤖 AI Actual Result: {search_keyword}")
                    ai_interpreted = search_keyword
                    results = search_mechanics_in_db(
                        query_keyword=search_keyword,
                        category=category,
                        min_rating=int(min_rating),
                        is_available=is_available,
                        sort_by=sort_by,
                        user_lat=user_lat,
                        user_lng=user_lng,
                    )
            else:
                # لو اليوزر كاتب اسم (زي إيمان صالح) وملوش بروفايل كامل، الكود هيطنش الـ AI وهيرجع فاضي.
                print(
                    f"🛑 Skipped AI: '{clean_q}' is treated as a name, no fallback applied."
                )

        print(
            f"DEBUG: Final Search for '{search_keyword}' with min_rating {min_rating}"
        )

        # 3. الرد النهائي
        return {
            "status": "success",
            "metadata": {
                "original_query": q,
                "ai_interpreted_as": ai_interpreted,
                "results_count": len(results) if results else 0,
            },
            "data": results if results else [],  # بنضمن إنها ترجع ليست فاضية [] مش Null
        }
    except Exception as e:
        print(f"❌ Database Error: {e}")
        raise HTTPException(status_code=500, detail=f"Database Error: {str(e)}")


@app.get("/search/suggest")
async def suggest_endpoint(
    q: str = Query(..., description="الكلمة اللي اليوزر بيكتبها (حرفين على الأقل)")
):
    """الاقتراحات التلقائية أثناء الكتابة (FR-3)"""
    if len(q) < 2:
        return {"status": "success", "data": []}

    results = get_search_suggestions_from_db(q)

    if results is None:
        raise HTTPException(
            status_code=500, detail="حدث خطأ في الاتصال بقاعدة البيانات."
        )

    return {"status": "success", "data": results}


# =====================================================================
# [ 8. تفاصيل الفني - Detailed View (FR-5) ]
# =====================================================================
@app.get("/mechanic/{mechanic_id}")
async def get_mechanic_details(mechanic_id: str):
    """جلب البيانات الكاملة للفني عند اختياره من النتائج (FR-5)"""
    mechanic = None  # نعرف المتغير بره الأول
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
                mp.Location_Latitude, mp.Location_Longitude, 
                0 AS YearsOfExperience, 
                '' AS Bio, 
                COALESCE(AVG(CAST(br.Stars AS FLOAT)), 0) AS Rating, 
                s.Name AS Specialty
            FROM dbo.Users u
            INNER JOIN dbo.MechanicProfile mp ON u.Id = mp.UserId
            LEFT JOIN dbo.Specializations s ON mp.Id = s.MechanicProfileId
            LEFT JOIN dbo.BookingRatings br ON u.Id = br.MechanicId
            WHERE u.Id = '{mechanic_id}'
            GROUP BY u.Id, u.FirstName, u.LastName, u.Phone, u.Email, mp.Location_Latitude, mp.Location_Longitude, s.Name
        """
        cursor.execute(sql)
        mechanic = cursor.fetchone()
        conn.close()

    except Exception as e:
        print(f"❌ Database Error: {e}")
        raise HTTPException(status_code=500, detail="حدث خطأ في قاعدة البيانات.")

    # نحط الـ 404 بره الـ try عشان ميتحولش لـ 500
    if not mechanic:
        raise HTTPException(status_code=404, detail="الفني غير موجود.")

    return {"status": "success", "data": mechanic}


# # =====================================================================
# # [ 9. حفظ التذكيرات - Save Reminders ]
# # =====================================================================
# @app.post("/reminders/save")
# async def save_maintenance_reminder(request: SaveReminderRequest):
#     """
#     حفظ التذكير الذي اقترحه الـ AI في قاعدة البيانات (SQL Server)
#     """
#     result = add_reminder_to_db(
#         request.user_id,
#         request.car_id,
#         request.title,
#         request.description,
#         request.suggested_date,
#         request.frequency,
#         request.notification_time,
#     )
#
#     if result:
#         return {"status": "success", "message": "تم حفظ التذكير بنجاح يا جيهاد! 🛠️"}
#     else:
#         raise HTTPException(
#             status_code=500, detail="عذراً، فشل الاتصال بقاعدة البيانات لحفظ التذكير."
#         )
