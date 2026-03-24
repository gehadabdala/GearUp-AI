# تعريف Pydantic Schemas
from pydantic import BaseModel
from typing import List, Optional

# =====================================================================
# [ 1. نماذج المحادثة الأساسية (Chat & History Models) ]
# =====================================================================
class Message(BaseModel):
    """
    نموذج يمثل رسالة واحدة داخل المحادثة.
    يحتوي على دور المرسل (user أو model) ومحتوى الرسالة.
    """
    role: str
    content: str


class QueryRequest(BaseModel):
    """
    النموذج المستقبل من الفرونت إند عند إرسال رسالة جديدة للذكاء الاصطناعي.
    يحتوي على تاريخ المحادثة بالكامل لضمان احتفاظ الـ AI بسياق الحوار (Memory).
    """
    messages: List[Message]


# =====================================================================
# [ 2. نموذج الاستجابة والتوصيات (Recommendation Response Model) ]
# =====================================================================
from pydantic import BaseModel
from typing import List, Optional

class RecommendationResponse(BaseModel):
    """
    العقد (Contract) بين الباك إند والفرونت إند لنتيجة الفحص الذكي.
    هذا النموذج يحدد شكل الـ JSON النهائي الذي سيستقبله الفرونت إند لبناء واجهة المستخدم.
    """
    query: str
    ai_answer: str
    source_documents: List[dict]  # لعرض المصادر/الحالات السابقة التي اعتمد عليها الـ AI في التشخيص

    # --- علامات تحكم لواجهة المستخدم (UI Control Flags) ---
    requires_feedback: bool = False  # إشارة للفرونت لإظهار أزرار التقييم (👍/👎) في حالات الصيانة فقط
    requires_mechanic: bool = False  # إشارة للفرونت لإظهار زر "اطلب فني طوارئ الآن" عند الأعطال الحرجة
    offers_reminder: bool = False    # إشارة للفرونت لإظهار زر "جدولة تذكير" في حالات طلب نصائح الصيانة الدورية

    # --- بيانات الحجز والربط مع النظام الأساسي (Booking & Context Data) ---
    recommended_mechanics: List[dict] = []  # قائمة الفنيين المرشحين بالـ IDs والإحداثيات لعرضهم على الخريطة
    car_id: Optional[str] = None            # إرجاع ID السيارة للفرونت لاستخدامه كـ Auto-fill في فورم طلب الصيانة
    issue_summary: Optional[str] = None     # إرجاع وصف مختصر للمشكلة لاستخدامه كـ Auto-fill في فورم الطلب


# =====================================================================
# [ 3. نماذج توثيق الفنيين (Mechanic Approval & OCR Models) ]
# =====================================================================
class ApprovalRequest(BaseModel):
    """
    النموذج المستقبل عند محاولة الفني رفع مستند لتوثيق حسابه.
    """
    mechanic_id: str
    doc_type: str     # نوع المستند المرفوع (مثل: commercial_reg, tax_card, national_id)
    image_data: str   # الصورة المرفوعة بعد تحويلها لصيغة Base64 لتمريرها لموديل الرؤية البصرية


class ApprovalResponse(BaseModel):
    """
    نموذج الرد على عملية الفحص بالذكاء الاصطناعي (OCR).
    يحتوي على حالة القبول، رسالة توضيحية للفني، ونسبة الثقة في المستند.
    """
    status: str       # حالة الطلب (مثلاً: approved, rejected, needs_manual_review)
    message: str      # تفاصيل أو سبب الرفض/القبول المستخرج من الذكاء الاصطناعي
    score: int        # نسبة الثقة في صحة المستند وقابليته للقراءة (من 0 إلى 100)