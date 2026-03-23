import json
import base64
from typing import Optional

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

# ==========================================
# تهيئة المتغيرات العالمية
# ==========================================
db = None
ai = None
approval_service = ApprovalService()


def safe_db_call(func):
    """دالة حماية عشان الكود ميفصلش لو الداتابيز وقعت"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(f"❌ Database Error in {func.__name__}: {e}")
            return None

    return wrapper


# ==========================================
# دوال قاعدة البيانات (Database Helpers)
# ==========================================
@safe_db_call
def get_mechanics_from_db(specialty: str, sub_specialty: str):
    """دالة للبحث عن الميكانيكية مع إعطاء الأولوية للتخصص الدقيق (الأدق)"""
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
                -- 👈 ضفنا الـ رتبة هنا عشان الـ DISTINCT يسمح بالترتيب
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
                mp.IsAvailable = 1 
                AND (s.Name LIKE N'%{specialty}%' OR ss.Name LIKE N'%{sub_specialty}%')
            ORDER BY Rank -- 👈 بنرتب بالاسم المستعار اللي عرفناه فوق
        """
    cursor.execute(query)
    mechanics = cursor.fetchall()
    conn.close()
    return mechanics


@safe_db_call
def get_user_context_data(user_id: str, car_id: Optional[str] = None):
    if not user_id: return None

    conn = pymssql.connect(
        server=settings.DB_SERVER, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME,
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
def get_mechanic_schedule(mechanic_name: str):
    """دالة لجلب المواعيد المتاحة لميكانيكي محدد بالاسم (محمية)"""
    conn = pymssql.connect(
        server=settings.DB_SERVER,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
    )
    cursor = conn.cursor(as_dict=True)

    query = f"""
        SELECT AvailableDate, StartTime, EndTime 
        FROM dbo.MechanicSchedules ms
        INNER JOIN dbo.MechanicProfile mp ON ms.MechanicProfileId = mp.Id
        INNER JOIN dbo.Users u ON mp.UserId = u.Id
        WHERE (u.FirstName + ' ' + u.LastName) LIKE N'%{mechanic_name}%'
        AND ms.IsBooked = 0
    """
    cursor.execute(query)
    schedules = cursor.fetchall()
    conn.close()
    return schedules


# ==========================================
# أحداث تشغيل السيرفر (Startup Events)
# ==========================================
@app.on_event("startup")
async def startup_event():
    global db, ai
    from app.database import VectorDB
    from app.ai_service import AIService

    db = VectorDB()
    ai = AIService()

    # تحميل البيانات من الإكسيل

    # db.ingest_excel()
    # تحميل البيانات
    db.ingest_data()


# ==========================================
# مسارات الـ API (Endpoints)
# ==========================================
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
            # 1. التحقق من صيغة الصورة (يُسمح فقط بـ JPG و PNG)
            if file.content_type not in ["image/jpeg", "image/png"]:
                raise HTTPException(status_code=400, detail="يُسمح فقط بصيغ JPG و PNG للمرفقات.")

            contents = await file.read()

            # 2. التحقق من حجم الصورة (الحد الأقصى 5 ميجابايت)
            if len(contents) > 5 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="حجم الصورة يتجاوز الحد المسموح (5 ميجابايت).")

            encoded = base64.b64encode(contents).decode("utf-8")
            image_data_url = f"data:{file.content_type};base64,{encoded}"

        # 2. جلب سياق المستخدم (اللي أنتي كنتِ كاتباه بالظبط)
        user_data = get_user_context_data(user_id, car_id)
        user_context = ""
        if user_data:
            f_name = user_data.get("FirstName", "يا صديقي")
            car_brand = user_data.get("Brand", "")
            car_model = user_data.get("Model", "")
            car_year = user_data.get("Year", "")
            user_context = f"[معلومة سرية: اسم المستخدم {f_name}، سيارته {car_brand} {car_model} موديل {car_year}. استخدم صيغة المذكر/المؤنث الصح واذكر اسم سيارته بلطافة.]"

        # 3. الكلمات المفتاحية (اللي أنتي كنتِ حطاها)
        # ضفنا كلمات الصيانة لـ car_keywords
        car_keywords = [
            "صوت",
            "خبط",
            "رائحة",
            "دواسة",
            "فتيس",
            "موتور",
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
            "موعد",
            "جدول"
        ]

        greeting_keywords = [
            "مين",
            "عرفني",
            "أنت",
            "اهلا",
            "سلام",
            "وظيفتك",
            # "بتعمل",
            "صباح",
            "مساء",
        ]

        is_car_related = any(word in description.lower() for word in car_keywords)
        is_greeting = any(word in description.lower() for word in greeting_keywords)

        # 4. البحث في قاعدة البيانات
        search_results = db.search(description, n_results=1)
        distances = search_results.get("distances", [[]])[0]
        is_far_match = not distances or distances[0] > 0.3

        # 5. منطق التحية والدردشة العامة
        if is_greeting or (not is_car_related and is_far_match):
            # 👈 عدلنا التعليمات عشان لو سأل عن صيانة يرد بنصيحة مش بتحية بس
            instructions = "أنت GearUp AI، خبير سيارات ودود. إذا كان المستخدم يطلب نصائح صيانة دورية، قدم له نصائح مبسطة وغير معقدة. وإذا كانت مجرد تحية، رد بلباقة وذكره بتخصصك."
            ai_chat_answer = await ai.generate_response(
                messages, [user_context, instructions], image_data_url
            )
            return RecommendationResponse(
                query=description, ai_answer=ai_chat_answer, source_documents=[], requires_feedback=False
            )

        # === [إضافة جديدة: منطق فحص مواعيد الورش] ===
        schedule_keywords = ["مواعيد", "وقت", "فاضي", "ساعة", "متاح", "يوم"]
        asking_for_schedule = any(
            word in description.lower() for word in schedule_keywords
        )
        schedule_text = ""

        if asking_for_schedule:
            extracted_name = description.lower()
            for word in schedule_keywords + [
                "ورشة",
                "المهندس",
                "ميكانيكي",
                "يا",
                "GearUp",
            ]:
                extracted_name = extracted_name.replace(word, "")
            extracted_name = extracted_name.strip()

            if extracted_name:
                schedules = get_mechanic_schedule(extracted_name)
                if schedules:
                    schedule_text = f"\n📅 المواعيد المتاحة لـ {extracted_name} هي:\n"
                    for s in schedules:
                        schedule_text += f"- يوم {s['AvailableDate']} من {s['StartTime']} إلى {s['EndTime']}\n"
                else:
                    schedule_text = f"\n(للأسف لم أجد مواعيد مسجلة حالياً لـ {extracted_name} في النظام)."
        # ============================================

        # 6. استخراج بيانات العطل (صعب/متوسط/سهل)
        metadata_list = search_results["metadatas"][0]
        top_case = metadata_list[0]
        difficulty = str(top_case.get("مستوى الصعوبة", "سهل")).strip()
        suggested_part = top_case.get("القطعة المرشحة", "غير محدد")
        suggested_solution = top_case.get("الحل المقترح", "يرجى الفحص")

        # الكلمات الحساسة اللي أنتي حددتيها
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
            "ضفيرة"
        ]
        contains_serious_word = any(
            word in description.lower() for word in serious_words
        )
        user_asking_for_workshop = any(
            word in description.lower()
            for word in ["ورشة", "ميكانيكي", "فني", "مركز صيانة", "تصليح"]
        )

        # 7. جلب الميكانيكية واللوكيشن
        mechanics_text = ""
        extracted_mechanics_list = []
        is_hard_issue = False

        # بنحدد لو العطل "صعب" أو فيه كلمات خطر أو اليوزر طلب ورشة
        if difficulty == "صعب" or contains_serious_word or user_asking_for_workshop:
            is_hard_issue = True  # هنا بنأكد إنها مشكلة محتاجة ميكانيكي

            specialty_json = await ai.extract_specialty(description, suggested_part)
            mechanics_list = get_mechanics_from_db(
                specialty_json.get("specialty", "ميكانيكا"),
                specialty_json.get("sub_specialty", ""),
            )

            if mechanics_list:
                extracted_mechanics_list = mechanics_list
                mechanics_text = "\n\nإليك الفنيين المتاحين حالياً في نظامنا:\n"
                for m in mechanics_list:
                    lat = m.get('Latitude', 0)
                    lng = m.get('Longitude', 0)
                    map_link = f"https://www.google.com/maps?q={lat},{lng}"
                    mechanics_text += f"- المهندس: {m.get('Name')} | 📞: {m.get('Phone')} | 📍 اللوكيشن: {map_link}\n"
            else:
                mechanics_text = "\n\n(للأسف لم أجد فنيين متاحين حالياً، أنصحك بالتوجه لأقرب مركز صيانة معتمد)."

        # 8. بناء الرد النهائي وتجهيز التعليمات (Instructions)
        if asking_for_schedule and schedule_text:
            instructions = f"اليوزر يسأل عن مواعيد ورشة {extracted_name}. بيانات المواعيد: {schedule_text}. {user_context}. رد عليه بلباقة وأخبره بالمواعيد المتاحة."

        elif is_hard_issue:  # 👈 استعملنا المتغير اللي عرفناه فوق بدل ما نعيد الشروط
            if extracted_mechanics_list:
                instructions = f"عطل حرج! {user_context}. حذر المستخدم. يجب أن تدرج قائمة الفنيين التالية كما هي بالنص: {mechanics_text}"
            else:
                instructions = f"عطل حرج! {user_context}. حذر المستخدم. ثم اعتذر له وأخبره بهذا النص حرفياً: {mechanics_text}"

        elif difficulty == "متوسط":
            instructions = f"{user_context} الحل: {suggested_solution}. التنسيق: ⚠️ ملاحظة هامة (اطمنه)، ⚙️ إيه المشكلة والحل؟، 👨‍🔧 نصيحة الخبير."

        else:
            instructions = f"{user_context} الحل: {suggested_solution}. التنسيق: ✅ لا تقلق الموضوع بسيط، 🛠️ خطوات الحل (استخدم إيموجي لكل خطوة)."

        ai_final_answer = await ai.generate_response(messages, [instructions], image_data_url)

        # 9. الـ Return النهائي (كل القيم دلوقتى مضمونة)
        return RecommendationResponse(
            query=description,
            ai_answer=ai_final_answer,
            source_documents=[top_case],
            requires_feedback=True,
            requires_mechanic=is_hard_issue,
            recommended_mechanics=extracted_mechanics_list
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/approve-mechanic")
async def approve_mechanic(
    mechanic_id: str = Form(...),
    doc_type: str = Form(...),
    file: UploadFile = File(...),
):
    contents = await file.read()
    encoded = base64.b64encode(contents).decode("utf-8")
    image_data_url = f"data:{file.content_type};base64,{encoded}"

    result = await approval_service.verify_document(
        doc_type=doc_type, image_data=image_data_url
    )
    return result


# ==========================================
# 9. نظام تقييم الردود (Feedback System)
# ==========================================
@app.post("/feedback")
async def submit_feedback(
    user_id: str = Form(...),
    query: str = Form(...),
    is_helpful: bool = Form(...),
):
    """دالة لتسجيل تقييم المستخدم لرد الـ AI"""
    try:
        conn = pymssql.connect(
            server=settings.DB_SERVER,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME
        )
        cursor = conn.cursor()

        # استعلام لإدخال التقييم
        query_sql = """
                    IF EXISTS (SELECT 1 FROM dbo.AI_Feedback WHERE UserId = %s AND UserQuery = %s)
                        UPDATE dbo.AI_Feedback SET IsHelpful = %s, CreatedAt = GETDATE() WHERE UserId = %s AND UserQuery = %s
                    ELSE
                        INSERT INTO dbo.AI_Feedback (UserId, UserQuery, IsHelpful, CreatedAt) VALUES (%s, %s, %s, GETDATE())
                """
        cursor.execute(query_sql, (user_id, query, is_helpful, user_id, query, user_id, query, is_helpful))

        conn.commit()
        conn.close()
        return {"status": "success", "message": "تم تسجيل التقييم بنجاح."}

    # print(
    #   f"DEBUG: Feedback Received -> User: {user_id}, Query: {query}, Helpful: {is_helpful}"
    # )
    # return {
    #    "status": "success",
    #    "message": "التيست اشتغل يا جيهاد! الداتا وصلت للـ Terminal.",
    # }
    # return {"status": "success", "message": "شكراً لتقييمك! بنتعلم من ملاحظاتك."}

    except Exception as e:
        print(f"Feedback Error: {e}")
        # حتى لو التقييم فشل مش عايزين نضرب Error لليوزر، نعديها عادي
        return {"status": "error", "message": "حصلت مشكلة بسيطة وإحنا بنسجل تقييمك."}


# ==========================================
# 10. نظام طلب فني للتدخل السريع (Request a Mechanic)
# ==========================================
@app.post("/request-mechanic")
async def request_mechanic(
        user_id: str = Form(...),
        mechanic_id: str = Form(...),
        car_id: Optional[str] = Form(None),
        issue_description: Optional[str] = Form("طلب تدخل فني لعطل حرج")
):
    """اليوزر بيطلب ميكانيكي يجيله فوراً لأن العطل تصنيفه (صعب) ولا يمكن حله يدوياً"""
    try:
        conn = pymssql.connect(
            server=settings.DB_SERVER,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME
        )
        cursor = conn.cursor()

        # إدخال طلب خدمة فوري في جدول ServiceRequests
        query = """
            INSERT INTO dbo.ServiceRequests (CustomerId, MechanicId, CarId, Description, Status, CreatedAt)
            VALUES (%s, %s, %s, %s, 'Pending', GETDATE())
        """
        # بنمرر البيانات للكوري عشان تتسجل في الداتا بيز
        cursor.execute(query, (user_id, mechanic_id, car_id, issue_description))

        conn.commit()
        conn.close()

        # إشعار وهمي في اللوج عشان تبقي عارفة إن الريكويست وصل
        print(f"🚨 URGENT Notification: ميكانيكي {mechanic_id} جالك طلب تدخل سريع من يوزر {user_id}")

        return {
            "status": "success",
            "message": "تم إرسال طلب التدخل بنجاح! الفني هيتواصل معاك فوراً."
        }

    except Exception as e:
        print(f"Mechanic Request Error: {e}")
        return {
            "status": "error",
            "message": "فشل إرسال الطلب، تأكد من اتصالك بالإنترنت أو حاول مرة أخرى."
        }