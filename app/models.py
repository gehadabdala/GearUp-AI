# تعريف Pydantic Schemas

from pydantic import BaseModel
from typing import List, Optional


class Message(BaseModel):
    role: str
    content: str


class QueryRequest(BaseModel):
    messages: list[
        Message
    ]  # History of messages in the conversation, including the user's query and previous interactions


class RecommendationResponse(BaseModel):
    query: str
    ai_answer: str
    source_documents: List[dict]  # لعرض المصادر التي اعتمد عليها الـ AI
    requires_feedback: bool = False #عشان نضمن إن الزراير تظهر بس وقت الأعطال والصيانة (ومش في التحيات)
    requires_mechanic: bool = False  # 👈 الإشارة للفرونت عشان يظهر زراير الطلب
    recommended_mechanics: list = []  # 👈 اللستة اللي الفرونت هياخد منها الـ IDs


# موديل طلب التوثيق
class ApprovalRequest(BaseModel):
    mechanic_id: str
    doc_type: str  # مثل: commercial_reg, tax_card, national_id
    image_data: str  # الوثيقه اللي هيرفعها الميكانيكي


# موديل رد التوثيق
class ApprovalResponse(BaseModel):
    status: str
    message: str
    score: int
