# تعريف Pydantic Schemas

from pydantic import BaseModel
from typing import List, Optional

class QueryRequest(BaseModel):
    description: str

class RecommendationResponse(BaseModel):
    query: str
    ai_answer: str
    source_documents: List[dict] # لعرض المصادر التي اعتمد عليها الـ AI


# موديل طلب التوثيق
class ApprovalRequest(BaseModel):
    mechanic_id: str
    doc_type: str  # مثل: commercial_reg, tax_card, national_id
    image_data: str # الوثيقه اللي هيرفعها الميكانيكي
# موديل رد التوثيق
class ApprovalResponse(BaseModel):
    status: str
    message: str
    score: int
    