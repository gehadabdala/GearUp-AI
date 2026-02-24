import re
from app.ai_service import AIService

class ApprovalService:
    def __init__(self):
        self.ai = AIService()
        # أنماط الوثائق المصرية الشائعة
        self.patterns = {
            "commercial_reg": r'^\d{5,9}$', # السجل التجاري
            "tax_card": r'^\d{3}-\d{3}-\d{3}$', # البطاقة الضريبية (رقم التسجيل الضريبي) (xxx-xxx-xxx)
            "national_id": r'^[23]\d{13}$' # الرقم القومي (14 رقم بيبدأ بـ 2 أو 3)
        }

    async def verify_document(self, doc_type: str, doc_content: str):
        doc_content = str(doc_content).strip() # تنظيف النص من أي مسافات
        
        # 1. التحقق من النمط (Pattern Matching)
        pattern = self.patterns.get(doc_type)
        is_pattern_valid = False
        if pattern:
            is_pattern_valid = bool(re.match(pattern, doc_content))
        
        print(f"DEBUG: Pattern Check for {doc_type}: {is_pattern_valid}")

        # 2. استخدام الذكاء الاصطناعي (خلينا نخلي الـ Prompt أوضح)
        prompt = f"""
        تحقق من منطقية الرقم التالي لوثيقة من نوع ({doc_type}):
        الرقم: {doc_content}
        إذا كان الرقم يتكون من 14 رقم ويبدأ بـ 2 أو 3 فهو رقم قومي مصري منطقي.
        رد بكلمة واحدة فقط: "Valid" أو "Invalid".
        """
        
        try:
            ai_analysis = await self.ai.generate_response(prompt, [])
            is_ai_valid = "Valid" in ai_analysis
            print(f"DEBUG: AI Check: {is_ai_valid} (Response: {ai_analysis})")
        except:
            is_ai_valid = True 

        # 3. القرار النهائي
        # لو النمط صح، هنمشيها Approved حتى لو الـ AI هنج
        if is_pattern_valid:
            return {
                "status": "Approved",
                "score": 100,
                "message": "تم قبول الوثيقة وتوثيق الحساب بنجاح."
            }
        else:
            return {
                "status": "Rejected",
                "score": 0,
                "message": "البيانات المدخلة غير مطابقة للنمط المطلوب. يرجى التأكد من إدخال 14 رقم صحيح للرقم القومي."
            }