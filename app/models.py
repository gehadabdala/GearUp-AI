# تعريف Pydantic Schemas
from pydantic import BaseModel
from typing import List, Optional


# =====================================================================
# [ 1. نماذج المحادثة الأساسية (Chat & History Models) ]
# =====================================================================
class Message(BaseModel):
    """
    نموذج يمثل رسالة واحدة داخل المحادثة.
    يحتوي على دور المرسل (user أو model) ومحتوى الرسالة النصي.
    """
    role: str
    content: str


class QueryRequest(BaseModel):
    """
    النموذج المستقبل من واجهة المستخدم عند إرسال استفسار جديد.
    يحتوي على قائمة الرسائل السابقة لضمان استمرارية سياق الحوار (Conversation Context).
    """
    messages: List[Message]


# =====================================================================
# [ 2. نموذج الاستجابة والتوصيات (Recommendation Response Model) ]
# =====================================================================
class RecommendationResponse(BaseModel):
    """
    العقد النهائي (Contract) لنتائج الفحص الذكي وتوصيات الصيانة.
    يتم استهلاكه بواسطة الفرونت إند لبناء واجهة المستخدم وتفعيل الأزرار والخرائط.
    """

    query: str                      # نص سؤال المستخدم الأصلي
    ai_answer: str                  # الرد التحليلي المفصل المولّد بواسطة الذكاء الاصطناعي
    source_documents: List[dict]    # الحالات المشابهة المستخرجة من قاعدة البيانات (RAG)

    # --- علامات التحكم المنطقية لواجهة المستخدم (UI Logical Control Flags) ---
    is_emergency: bool = False      # هل الرد حالة طوارئ؟
    is_advice_mode: bool = False    # هل الرد مجرد نصيحة عامة؟ (True تعني إيقاف وضع الطوارئ)
    requires_mechanic: bool = False # هل الحالة تستدعي إظهار زر "اطلب فني طوارئ الآن"؟
    offers_reminder: bool = False   # هل الحالة تسمح بإظهار زر "جدولة تذكير صيانة"؟
    requires_feedback: bool = False # هل يجب إظهار أزرار التقييم (👍/👎) للمستخدم؟
    use_current_location: bool = False # هل يجب على التطبيق طلب تفعيل الـ GPS فوراً؟
    has_attachment: bool = False    # إشارة بوجود ملف مرفق (صورة) تم تحليلها في الرد

    # --- بيانات الربط مع النظام (System Context & Mapping) ---
    recommended_mechanics: List[dict] = [] # قائمة الفنيين المقترحين مع بيانات التواصل والموقع
    car_id: Optional[str] = None           # معرف السيارة المستخدم في العملية لربط الطلبات
    issue_summary: Optional[str] = None    # ملخص فني للمشكلة للملء التلقائي في نماذج الحجز

    # --- بيانات الملء التلقائي لتذكيرات الصيانة (Auto-fill: Reminders) ---
    suggested_reminder_title: Optional[str] = None
    suggested_reminder_desc: Optional[str] = None
    suggested_frequency: Optional[str] = None # 'يومي', 'شهري', 'كل 10,000 كم' ... إلخ
    suggested_date: Optional[str] = None      # تاريخ البداية المقترح (YYYY/MM/DD)
    suggested_end_date: Optional[str] = None  # تاريخ انتهاء التذكير إن وجد
    notification_time: Optional[str] = None   # وقت الإشعار المفضل (مثلاً: 09:00 AM)

    # --- بيانات الملء التلقائي لطلبات الطوارئ (Auto-fill: Emergency/Booking) ---
    service_type: Optional[str] = None          # 'خدمة طارئة' أو 'صيانة مجدولة'
    required_service: Optional[str] = None      # نوع الخدمة الفنية (مثلاً: 'ميكانيكا محرك')
    service_location_type: Optional[str] = None # 'في الورشة' أو 'ميكانيكي متنقل'


# =====================================================================
# [ 3. نماذج توثيق الفنيين (Mechanic Approval & OCR Models) ]
# =====================================================================
class ApprovalRequest(BaseModel):
    """
    النموذج المستقبل عند محاولة الفني توثيق حسابه الرسمي.
    يمرر صورة المستند (Base64) ونوعه لتحليله عبر موديلات الرؤية البصرية.
    """
    mechanic_id: str
    doc_type: str    # نوع الوثيقة: (رخصة ورشة، بطاقة ضريبية، بطاقة شخصية)
    image_data: str  # بيانات الصورة بتنسيق Base64


class ApprovalResponse(BaseModel):
    """
    نتيجة عملية الفحص الآلي للمستندات.
    """
    status: str      # الحالة: (approved: مقبول، rejected: مرفوض، pending: مراجعة يدوية)
    message: str     # التبرير أو النصائح المستخرجة من الوثيقة (مثل: "الرخصة منتهية الصلاحية")
    score: int       # نسبة الثقة في جودة وصحة المستند (0-100)