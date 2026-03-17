import json
import base64
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
import pymssql

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


# ==========================================
# دوال قاعدة البيانات (Database Helpers)
# ==========================================
def get_mechanics_from_db(specialty: str, sub_specialty: str):
    """دالة للبحث عن الميكانيكية المتاحين بناءً على التخصص بربط 4 جداول"""
    try:
        conn = pymssql.connect(
            server=settings.DB_SERVER,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME
        )
        cursor = conn.cursor(as_dict=True)

        query = f"""
            SELECT TOP 3 
                u.FirstName + ' ' + u.LastName AS Name, 
                u.Phone, 
                mp.Location_Latitude AS Latitude,
                mp.Location_Longitude AS Longitude
            FROM dbo.Users u
            INNER JOIN dbo.MechanicProfile mp ON u.Id = mp.UserId
            INNER JOIN dbo.Specialization s ON mp.Id = s.MechanicProfileId
            LEFT JOIN dbo.SubSpecialization ss ON s.Id = ss.SpecializationId
            WHERE 
                mp.IsAvailable = 1 
                AND (s.Name LIKE N'%{specialty}%' OR ss.Name LIKE N'%{sub_specialty}%')
        """
        cursor.execute(query)
        mechanics = cursor.fetchall()
        conn.close()
        return mechanics
    except Exception as e:
        print(f"Database Error: {e}")
        return []


def get_user_context_data(user_id: str):
    """دالة لجلب اسم المستخدم وماركة سيارته لتحديد صيغة المخاطبة"""
    if not user_id:
        return None

    try:
        conn = pymssql.connect(
            server=settings.DB_SERVER,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME
        )
        cursor = conn.cursor(as_dict=True)

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
    except Exception as e:
        print(f"Database Error (Context): {e}")
        return None


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

    # تحميل البيانات
    db.ingest_data()


# ==========================================
# مسارات الـ API (Endpoints)
# ==========================================
@app.post("/recommend", response_model=RecommendationResponse)
async def get_recommendation(
        query_data: str = Form(...),
        user_id: Optional[str] = Form(None),
        file: Optional[UploadFile] = File(None),
):
    try:
        # 1. معالجة المدخلات
        try:
            data_dict = json.loads(query_data)
        except Exception:
            raise HTTPException(
                status_code=400, detail="query_data must be a valid JSON string"
            )

        messages_raw = data_dict.get("messages", [])
        if not messages_raw:
            raise HTTPException(
                status_code=400, detail="Message list is required in query_data"
            )

        messages = [Message(**m) for m in messages_raw]
        description = messages[-1].content

        image_data_url = None
        if file:
            contents = await file.read()
            encoded = base64.b64encode(contents).decode("utf-8")
            image_data_url = f"data:{file.content_type};base64,{encoded}"

        # 2. جلب بيانات سياق المستخدم
        user_data = get_user_context_data(user_id)
        user_context = ""

        if user_data:
            f_name = user_data.get("FirstName", "يا صديقي")
            car_brand = user_data.get("Brand", "")
            car_model = user_data.get("Model", "")
            car_year = user_data.get("Year", "")

            user_context = f"""
            [معلومة سرية لك: 
            - اسم المستخدم: {f_name}
            - سيارته: {car_brand} {car_model} موديل {car_year}. 
            - تعليمات هامة: استنتج نوع المستخدم (ذكر/أنثى) من الاسم ({f_name}) واستخدم ضمائر المخاطبة العربية الصحيحة. خصص إجابتك لتناسب سيارته واذكر اسمها بلطافة.]
            """
            print(f"👤 المستخدم: {f_name} | السيارة: {car_brand} {car_model}")

        # 3. البحث في قاعدة البيانات (Vector DB)
        search_results = db.search(description, n_results=1)
        distances = search_results.get("distances", [[]])[0]
        is_far_match = not distances or distances[0] > 1.5

        # 4. فلترة الكلمات المفتاحية
        car_keywords = [
            "صوت", "خبط", "رائحة", "دواسة", "فتيس", "موتور", "فرامل",
            "عجلة", "كاوتش", "بنزين", "حرارة", "زيت", "قير", "عطل",
            "بوجيهات", "مارش", "بطارية", "مساحات"
        ]
        greeting_keywords = ["مين", "عرفني", "أنت", "اهلا", "سلام", "وظيفتك", "بتعمل"]

        is_car_related = any(word in description.lower() for word in car_keywords)
        is_greeting = any(word in description.lower() for word in greeting_keywords)

        # الرد المباشر في حالة التحيات أو عدم وجود علاقة بالسيارات
        if is_greeting or not is_car_related or is_far_match:
            general_instructions = [user_context] if user_context else []
            ai_chat_answer = await ai.generate_response(messages, general_instructions, image_data_url)
            return RecommendationResponse(
                query=description, ai_answer=ai_chat_answer, source_documents=[]
            )

        # 5. استخراج البيانات من التطابق
        metadata_list = search_results["metadatas"][0]
        top_case = metadata_list[0]

        difficulty = str(top_case.get("مستوى الصعوبة", "سهل")).strip()
        suggested_part = top_case.get("القطعة المرشحة", "غير محدد")
        suggested_solution = top_case.get("الحل المقترح", "يرجى الفحص")

        serious_words = [
            "فتيس", "موتور", "محرك", "ناقل حركة", "جير", "عمرة",
            "شاسيه", "بيستم", "كنترول", "حرارة"
        ]
        contains_serious_word = any(word in description.lower() for word in serious_words)

        # ==========================================
        # 6. منطق اتخاذ القرار وتوليد الرد النهائي
        # ==========================================

        # --- العطل الحرج ---
        if difficulty == "صعب" or contains_serious_word:
            specialty_json = await ai.extract_specialty(description, suggested_part)
            spec = specialty_json.get("specialty", "")
            sub_spec = specialty_json.get("sub_specialty", "")

            print(f"🔍 التخصص المستخرج: {spec} | التخصص الفرعي: {sub_spec}")
            mechanics_list = get_mechanics_from_db(spec, sub_spec)
            print(f"👨‍🔧 الميكانيكية المتاحين: {mechanics_list}")

            mechanics_text = ""
            if mechanics_list:
                mechanics_text = "\n\nرشح للمستخدم هؤلاء الفنيين المتاحين في النظام للضرورة القصوى:\n"
                for m in mechanics_list:
                    mechanics_text += f"- المهندس: {m.get('Name', 'غير معروف')} | تليفون: {m.get('Phone', 'غير متوفر')}\n"
            else:
                mechanics_text = "\n\n(ملحوظة للذكاء الاصطناعي: لا يوجد فنيين متاحين، انصحه بالتوجه لأقرب مركز صيانة)."

            instructions = f"""المشكلة: {description}
            البيانات الإضافية:{user_context}
            الميكانيكية المتاحين:{mechanics_text}
            
            أنت مهندس سيارات خبير. هذا عطل حرج جداً.
            ممنوع الاعتذار أو ذكر نسبة التأكد.
            يجب أن يكون ردك حصرياً بهذا التنسيق المرتب (استخدم Markdown والإيموجيز):
            
            🚨 **تحذير عاجل:**
            (اطلب منه/منها إيقاف السيارة فوراً وطمئنه/ا بأسلوب ودود واذكر اسم سيارته/ا هنا)
            
            🛠️ **التشخيص المبدئي:**
            (اشرح باختصار شديد جداً وفي سطرين كحد أقصى سبب المشكلة)
            
            👨‍🔧 **فنيين متاحين للإنقاذ:**
            (اكتب هنا نص الميكانيكية المتاحين الذي تم تمريره لك بالظبط، وإذا لم يوجد، انصحه/ا بالتوجه لأقرب مركز)
            
            💡 **نصيحة سريعة:**
            (نصيحة واحدة قصيرة جداً لما يجب فعله أثناء انتظار المساعدة)
            """
            ai_final_answer = await ai.generate_response(messages, [instructions], image_data_url)

        # --- العطل المتوسط ---
        elif difficulty == "متوسط":
            instructions = f"""المشكلة: {description}
            البيانات الإضافية: {user_context}
            الحل المقترح من قاعدة البيانات: {suggested_solution}
            
            أنت مهندس سيارات ودود. هذا عطل متوسط الخطورة.
            يجب أن يكون ردك حصرياً بهذا التنسيق المرتب (استخدم Markdown):
            
            ⚠️ **ملاحظة هامة:**
            (اكتب جملة لطيفة تطمئن المستخدم مع ذكر اسم سيارته هنا واستخدم صيغة المذكر أو المؤنث الصحيحة)    
            
            ⚙️ **إيه المشكلة والحل؟**
            (اشرح الحل المقترح بأسلوب مبسط ومفهوم)
            
            👨‍🔧 **نصيحة الخبير:**
            (انصح باستشارة فني في أقرب فرصة لضمان عدم تفاقم المشكلة)
            """
            ai_final_answer = await ai.generate_response(messages, [instructions], image_data_url)

        # --- العطل السهل ---
        else:
            instructions = f"""المشكلة: {description}
            البيانات الإضافية: {user_context}
            الحل المقترح من قاعدة البيانات: {suggested_solution}
            
            أنت مساعد سيارات ذكي وودود. هذا عطل سهل جداً ويمكن حله بنفسك.
            يجب أن يكون ردك حصرياً بهذا التنسيق المرتب:
            
            ✅ **لا تقلق! الموضوع بسيط:**
            (طمئن المستخدم واستخدم صيغة المذكر أو المؤنث الصحيحة بناء على الاسم واذكر اسم سيارته)
            
            🛠️ **خطوات الحل (جربها بنفسك):**
            (اشرح الحل المقترح في خطوات مرقمة وبسيطة جداً مع استخدام رموز تعبيرية لكل خطوة)
            """
            ai_final_answer = await ai.generate_response(messages, [instructions], image_data_url)

        return RecommendationResponse(
            query=description, ai_answer=ai_final_answer, source_documents=[top_case]
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"حدث خطأ في النظام: {str(e)}")


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