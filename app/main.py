from fastapi import FastAPI, HTTPException , UploadFile, File, Form
import base64

from app.models import QueryRequest, RecommendationResponse, ApprovalRequest, ApprovalResponse

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

async def get_recommendation(request: QueryRequest):

    try:

        # 1. البحث في قاعدة البيانات

        search_results = db.search(request.description, n_results=3)

        distances = search_results.get('distances', [[]])[0]

       

        car_keywords = ["صوت", "خبط", "رائحة", "دواسة", "فتيس", "موتور", "فرامل", "عجلة", "كاوتش", "بنزين", "حرارة", "زيت", "قير", "عطل", "بوجيهات", "مارش", "بطارية"]

        is_car_related = any(word in request.description.lower() for word in car_keywords)

       

        # 2. فلتر الرفض (خارج التخصص)
        is_far_match = not distances or distances[0] > 0.6

        if not is_car_related or is_far_match:
            
            ai_chat_answer = await ai.generate_response(request.description, [])
            return RecommendationResponse(

                query=request.description,

                ai_answer=ai_chat_answer,

                source_documents=[]

            )



        # 3. استخراج البيانات والـ Metadata

        context_documents = search_results['documents'][0]

        metadata_list = search_results['metadatas'][0]

        top_case = metadata_list[0]

       

        difficulty = str(top_case.get('مستوى الصعوبة', 'سهل')).strip()

        suggested_part = top_case.get('القطعة المرشحة', 'غير محدد')

        suggested_solution = top_case.get('الحل المقترح', 'يرجى الفحص')

        category = top_case.get('الفئة', 'عام')



        # 4. فحص الكلمات الحساسة

        serious_words = ["فتيس", "موتور", "محرك", "ناقل حركة", "جير", "عمرة", "شاسيه", "بيستم", "كنترول", "حرارة"]

        contains_serious_word = any(word in request.description.lower() for word in serious_words)



        # --- منطق اتخاذ القرار (المعدل بناءً على طلبك) ---

       

        # الحالة الأولى: عطل صعب (توجيه مباشر وحازم)

        if difficulty == "صعب" or contains_serious_word:

            ai_final_answer = (

                f"🚨 عطل عالي الخطورة (المستوى: {difficulty})\n"

                f"القطعة المرشحة: {suggested_part}\n"

                f"الفئة: {category}\n\n"

                "⚠️ التوجيه: هذا العطل حرج جداً ولا يمكن إصلاحه يدوياً. "

                "من أجل سلامتك وتجنب تلف أجزاء أخرى، يجب التوجه فوراً لميكانيكي متخصص."

            )

       

        # الحالة الثانية: عطل متوسط (إعطاء الحل + نصيحة بالذهاب للميكانيكي)

        elif difficulty == "متوسط":

            try:

                prompt = f"المشكلة: {request.description}\nالحل الفني: {suggested_solution}\nصغ هذا الحل بطريقة ودودة، ووضح للمستخدم أنه يفضل استشارة فني لضمان السلامة."

                ai_answer_raw = await ai.generate_response(prompt, [])

               

                ai_final_answer = (

                    f"⚠️ تنبيه: عطل متوسط الصعوبة في ({suggested_part})\n\n"

                    f"{ai_answer_raw}\n\n"

                    "💡 نصيحة GearUp: رغم أن الحل متاح، إلا أننا ننصحك بزيارة ميكانيكي متخصص لضمان جودة الإصلاح وأمانك."

                )

            except Exception:

                ai_final_answer = (

                    f"⚠️ عطل متوسط الصعوبة في ({suggested_part})\n"

                    f"الحل المقترح: {suggested_solution}\n\n"

                    "💡 يفضل استشارة ميكانيكي متخصص للقيام بهذا الإصلاح."

                )



        # الحالة الثالثة: عطل سهل (حل مباشر)

        else:

            try:

                prompt = f"المشكلة: {request.description}\nالحل الفني: {suggested_solution}\nصغ هذا الحل بخطوات سهلة وبسيطة."

                ai_final_answer = await ai.generate_response(prompt, [])

            except Exception:

                ai_final_answer = (

                    f"✅ عطل بسيط في ({suggested_part})\n"

                    f"الحل المقترح: {suggested_solution}"

                )



        return RecommendationResponse(

            query=request.description,

            ai_answer=ai_final_answer,

            source_documents=metadata_list

        )

       

    except Exception as e:

        raise HTTPException(status_code=500, detail=f"حدث خطأ في النظام: {str(e)}")



# --- الجزء الخاص بتوثيق الميكانيكي ---

@app.post("/approve-mechanic")
async def approve_mechanic(
    mechanic_id: str = Form(...),
    doc_type: str = Form(...),
    file: UploadFile = File(...) # ده اللي هيطلع زرار الرفع في الـ Swagger
):
    # 1. قراءة محتوى الصورة وتحويلها لـ Base64
    contents = await file.read()
    encoded = base64.b64encode(contents).decode("utf-8")
    # تجهيز الـ URL اللي OpenRouter بيفهمه
    image_data_url = f"data:{file.content_type};base64,{encoded}"
    
    # 2. إرسال البيانات للـ ApprovalService
    # (تأكدي إن الـ verify_document عندك بتنادي self.ai.get_ocr_text)
    result = await approval_service.verify_document(
        doc_type=doc_type,
        image_data=image_data_url
    )
    return result