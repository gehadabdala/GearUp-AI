from fastapi import FastAPI, HTTPException, UploadFile, File, Form
import base64

from app.models import (
    QueryRequest,
    RecommendationResponse,
    ApprovalRequest,
    ApprovalResponse,
)

from app.approval_service import ApprovalService


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

    db.ingest_excel()


@app.post("/recommend", response_model=RecommendationResponse)
async def get_recommendation(
    description: str = Form(...),  # وصف العطل (نص)
    file: UploadFile = File(None),  # صورة العطل (اختياري)
):
    try:
        image_data_url = None
        if file:
            contents = await file.read()
            encoded = base64.b64encode(contents).decode("utf-8")
            image_data_url = f"data:{file.content_type};base64,{encoded}"

        # 1. البحث السريع في قاعدة البيانات (قللنا النتائج لـ 1 لتسريع الرد)
        search_results = db.search(description, n_results=1)
        distances = search_results.get("distances", [[]])[0]

        # كلمات مفتاحية ذكية للتحقق السريع
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
        greeting_keywords = ["مين", "عرفني", "أنت", "اهلا", "سلام", "وظيفتك", "بتعمل"]

        is_car_related = any(word in description.lower() for word in car_keywords)
        is_greeting = any(word in description.lower() for word in greeting_keywords)

        # 2. فلتر الرفض والتعارف (ريكوست واحد فقط للـ AI في حالة عدم المطابقة)
        is_far_match = (
            not distances or distances[0] > 0.7
        )  # رفعنا الرقم لـ 0.7 لمرونة أكبر

        if not is_car_related or is_far_match:
            # بنادي الـ AI مرة واحدة بس هنا لو الكلام عام أو ملوش نتيجة في الإكسيل
            ai_chat_answer = await ai.generate_response(description, [], image_data_url)
            return RecommendationResponse(
                query=description, ai_answer=ai_chat_answer, source_documents=[]
            )

        # 3. استخراج البيانات (في حالة وجود تطابق في الإكسيل)
        metadata_list = search_results["metadatas"][0]
        top_case = metadata_list[0]

        difficulty = str(top_case.get("مستوى الصعوبة", "سهل")).strip()
        suggested_part = top_case.get("القطعة المرشحة", "غير محدد")
        suggested_solution = top_case.get("الحل المقترح", "يرجى الفحص")

        # 4. فحص الكلمات الحساسة للأعطال الحرجة
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

        # --- منطق اتخاذ القرار السريع ---
        if difficulty == "صعب" or contains_serious_word:
            prompt = (
                f"المشكلة: {description}\nالقطعة: {suggested_part}\n"
                "هذا عطل حرج. حذر المستخدم بصرامة من الإصلاح اليدوي واطلب منه التوجه للميكانيكي."
            )
            ai_final_answer = await ai.generate_response(prompt, [], image_data_url)

        elif difficulty == "متوسط":
            prompt = f"المشكلة: {description}\nالحل الفني: {suggested_solution}\nصغ الحل بودية وانصح باستشارة فني."
            ai_answer_raw = await ai.generate_response(prompt, [], image_data_url)
            ai_final_answer = f"⚠️ عطل متوسط في ({suggested_part})\n\n{ai_answer_raw}"

        else:  # عطل سهل
            prompt = f"المشكلة: {description}\nالحل: {suggested_solution}\nبسط الخطوات لليوزر العادي."
            ai_final_answer = await ai.generate_response(prompt, [], image_data_url)

        return RecommendationResponse(
            query=description, ai_answer=ai_final_answer, source_documents=metadata_list
        )

    except Exception as e:
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
