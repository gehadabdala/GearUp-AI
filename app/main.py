import json
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
import base64
from typing import Optional
from app.models import (
    QueryRequest,
    RecommendationResponse,
    ApprovalRequest,
    ApprovalResponse,
)

from app.approval_service import ApprovalService
from app.models import Message

app = FastAPI(title="GearUp Recommendation System")


# تهيئة المتغيرات العالمية

db = None

ai = None

approval_service = ApprovalService()


@app.on_event("startup")
async def startup_event():

    global db, ai

    from app.database import VectorDB

    from app.ai_service import AIService

    db = VectorDB()

    ai = AIService()

    # تحميل البيانات من الإكسيل

    # db.ingest_excel()


@app.post("/recommend", response_model=RecommendationResponse)
async def get_recommendation(
    query_data: str = Form(...),
    file: Optional[UploadFile] = File(None),
):
    try:
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

        # 1. البحث في قاعدة البيانات
        search_results = db.search(description, n_results=1)
        distances = search_results.get("distances", [[]])[0]
        # خليت المسافة 0.8 عشان ندي فرصة أكبر للبحث السيمانتك
        is_far_match = not distances or distances[0] > 0.8

        # 2. الكلمات المفتاحية (زي ما هي بالظبط)
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
        ]
        greeting_keywords = [
            "مين",
            "عرفني",
            "أنت",
            "اهلا",
            "سلام",
            "وظيفتك",
            "بتعمل",
            "صباح",
            "مساء",
        ]

        is_car_related = any(word in description.lower() for word in car_keywords)
        is_greeting = any(word in description.lower() for word in greeting_keywords)

        # 3. فلتر الرفض والتعارف (تعديل الـ Prompt هنا عشان يبقى أذكى)
        if is_greeting or (not is_car_related and is_far_match):
            instructions = "أنت GearUp AI، خبير سيارات ودود. رد على التحية أو الدردشة بذكاء. إذا كان الكلام بعيداً عن السيارات، ساعده بلباقة وذكره بتخصصك."
            ai_chat_answer = await ai.generate_response(
                messages, [instructions], image_data_url
            )
            return RecommendationResponse(
                query=description, ai_answer=ai_chat_answer, source_documents=[]
            )

        # 4. استخراج البيانات من الإكسيل (لو فيه تطابق)
        metadata_list = search_results["metadatas"][0]
        top_case = metadata_list[0]
        difficulty = str(top_case.get("مستوى الصعوبة", "سهل")).strip()
        suggested_part = top_case.get("القطعة المرشحة", "غير محدد")
        suggested_solution = top_case.get("الحل المقترح", "يرجى الفحص")

        # 5. فحص الكلمات الحساسة (زي ما هي)
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
        ]
        contains_serious_word = any(
            word in description.lower() for word in serious_words
        )

        # 6. منطق اتخاذ القرار (دمج معلومات الإكسيل مع ذكاء الـ AI)
        if difficulty == "صعب" or contains_serious_word:
            instructions = f"المشكلة: {description}\nالقطعة: {suggested_part}\nهذا عطل حرج وحساس. حذر المستخدم بجدية من الإصلاح اليدوي واشرح له العواقب، ووجهه لفني متخصص."
        elif difficulty == "متوسط":
            instructions = f"المشكلة: {description}\nالحل الفني من قاعدة بياناتنا: {suggested_solution}\nصغ الحل بأسلوب مهني وودود وانصح بالاستعانة بفني إذا لزم الأمر."
        else:  # عطل سهل
            instructions = f"المشكلة: {description}\nالحل المقترح: {suggested_solution}\nبسط الخطوات للمستخدم جداً واستخدم الرموز التعبيرية كخبير يشرح لمبتدئ."

        # هنا الـ AI هيستخدم الـ instructions عشان يطلع الرد النهائي العسل
        ai_final_answer = await ai.generate_response(
            messages, [instructions], image_data_url
        )

        return RecommendationResponse(
            query=description, ai_answer=ai_final_answer, source_documents=metadata_list
        )

    except Exception as e:
        # رجعنا الخطأ الحقيقي عشان لو فيه مشكلة في الـ API نعرفها
        raise HTTPException(status_code=500, detail=f"حدث خطأ في النظام: {str(e)}")


# --- الجزء الخاص بتوثيق الميكانيكي ---


@app.post("/approve-mechanic")
async def approve_mechanic(
    mechanic_id: str = Form(...),
    doc_type: str = Form(...),
    file: UploadFile = File(...),  # ده اللي هيطلع زرار الرفع في الـ Swagger
):
    # 1. قراءة محتوى الصورة وتحويلها لـ Base64
    contents = await file.read()
    encoded = base64.b64encode(contents).decode("utf-8")
    # تجهيز الـ URL اللي OpenRouter بيفهمه
    image_data_url = f"data:{file.content_type};base64,{encoded}"

    # 2. إرسال البيانات للـ ApprovalService
    # (تأكدي إن الـ verify_document عندك بتنادي self.ai.get_ocr_text)
    result = await approval_service.verify_document(
        doc_type=doc_type, image_data=image_data_url
    )
    return result
