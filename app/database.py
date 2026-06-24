import pandas as pd
import chromadb
from app.config import settings
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from sentence_transformers import SentenceTransformer


class LocalHuggingFaceEmbedder(EmbeddingFunction):
    def __init__(
        self, model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    ):
        # موديل محلي خفيف وممتاز جداً في فهم اللغة العربية والمصطلحات التقنية
        self.model = SentenceTransformer(model_name)

    def __call__(self, input: Documents) -> Embeddings:
        # تحويل النصوص لمتجهات بدون أي API Keys
        try:
            embeddings = self.model.encode(input).tolist()
            return embeddings
        except Exception as e:
            print("⚠️ Embedding Error:", e)
            return [[0.0] * 384] * len(input)  # 384 هو أبعاد الموديل الجديد


class VectorDB:
    def __init__(self):
        self.client = chromadb.Client()
        # استخدام كلاس الـ HuggingFace الجديد
        self.embedding_fn = LocalHuggingFaceEmbedder()
        self.collection = self.client.get_or_create_collection(
            name="gearup_knowledge", embedding_function=self.embedding_fn
        )

    def ingest_data(self):
        if self.collection.count() > 0:
            return
        try:
            df = pd.read_csv(settings.SHEET_URL)
            df = df.dropna(how="all").fillna("")
            documents, metadatas, ids = [], [], []

            for index, row in df.iterrows():
                problem = row.get("المشكلة") or row.get("العطل") or "غير محدد"
                description = row.get("وصف العطل") or row.get("الوصف") or ""
                solution = (
                    row.get("الحل المقترح") or row.get("الحل") or "يرجى الفحص الفني"
                )
                part = (
                    row.get("القطعة المرشحة")
                    or row.get("قطعة الغيار المرشحة")
                    or "غير محدد"
                )
                difficulty = str(row.get("مستوى الصعوبة") or "متوسط").strip()
                category = str(row.get("الفئة") or "عام")

                documents.append(
                    f"المشكلة: {problem}\nالوصف: {description}\nالحل: {solution}"
                )
                metadatas.append(
                    {
                        "القطعة المرشحة": str(part),
                        "الحل المقترح": str(solution),
                        "مستوى الصعوبة": difficulty,
                        "الفئة": category,
                    }
                )
                ids.append(f"id_{index}")

            # 🟢 تعديل مهم: بما إننا بنرن محلي، كبرنا الدفعة لـ 500 عشان يخلص أسرع بكتير!
            batch_size = 500
            for i in range(0, len(documents), batch_size):
                self.collection.add(
                    documents=documents[i : i + batch_size],
                    metadatas=metadatas[i : i + batch_size],
                    ids=ids[i : i + batch_size],
                )
            print(f"✅ تم الانتهاء! إجمالي السجلات: {len(documents)}")
        except Exception as e:
            print(f"❌ خطأ أثناء ingest: {str(e)}")

    def search(self, query: str, n_results: int = 3):
        results = self.collection.query(query_texts=[query], n_results=n_results)
        return results

    # الكود القديم المعمول له Comment سبتهولك زي ما هو لو احتجتيه كمرجع
    # def ingest_excel(self):
    # ... (باقي الأكواد المعطلة كما هي عندك)
