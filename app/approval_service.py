from ast import pattern
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

    async def verify_document(self, doc_type: str,image_data: str):
        prompt = f"استخرج رقم الـ {doc_type} من هذه الصورة. رد بالرقم فقط."
        try:
        
            extracted_text = await self.ai.get_ocr_text(prompt, image_data)
            doc_content = str(extracted_text).strip()
            print(f"DEBUG: الرقم اللي الـ AI قرأه: {doc_content}")

        except Exception as e:
            print(f"DEBUG: Error in AI OCR: {e}")
            return {"status": "Rejected", "message": "فشل قراءة الوثيقة، يرجى رفع صورة أوضح."}
        
        pattern = self.patterns.get(doc_type)
        is_pattern_valid = False
        clean_id = ""


        if pattern and doc_content:
            match = re.search(pattern, doc_content)
            if match:
                clean_id = match.group()
                is_pattern_valid = True

        # 3. القرار النهائي
        if is_pattern_valid:
            return {
                "status": "Approved",
                "extracted_number": clean_id,
                "message": f"تم التحقق من صحة {doc_type} وقبول التسجيل بنجاح."
            }
        else:
            return {
                "status": "Rejected",
                "message": f"الرقم ({doc_content}) لا يطابق شروط {doc_type}."
            }