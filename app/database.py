import pandas as pd
import chromadb
from chromadb.utils import embedding_functions
from app.config import settings
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
import httpx


class SafeGeminiEmbedding(EmbeddingFunction):
    def __call__(self, input: Documents) -> Embeddings:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/embedding-001:batchEmbedContents?key={settings.GEMINI_API_KEY}"
        reqs = [
            {"model": "models/embedding-001", "content": {"parts": [{"text": str(t)}]}}
            for t in input
        ]
        try:
            res = httpx.post(url, json={"requests": reqs}, timeout=50.0).json()
            if "embeddings" in res:
                return [item["values"] for item in res["embeddings"]]
            else:
                print("⚠️ Gemini API Error:", res)
        except Exception as e:
            print("⚠️ Network Error:", e)
        # لو حصل أي مشكلة، السيرفر مش هيقع وهيرجع داتا فاضية عشان يفضل شغال
        return [[0.0] * 768] * len(input)


class VectorDB:
    def __init__(self):
        self.client = chromadb.Client()
        # استخدمنا الكلاس الخفيف بتاعنا
        self.embedding_fn = SafeGeminiEmbedding()
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

            # 🔴 تعديل مهم جداً: جوجل آخرها 100 في الدفعة، فخلينا الدفعة 90 عشان ميرفضش الطلب
            batch_size = 90
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
        return self.collection.query(query_texts=[query], n_results=n_results)

    # def ingest_excel(self):
    #     """رفع البيانات على دفعات لتجنب خطأ الـ Batch Size"""
    #     if self.collection.count() > 0:
    #         print("Data already ingested (ChromaDB contains data).")
    #         return
    #
    #     df = pd.read_csv(settings.SHEET_URL)
    #     documents, metadatas, ids = [], [], []
    #
    #     for index, row in df.iterrows():
    #         content = f"العطل: {row['العطل']}\nالوصف: {row['وصف العطل']}\nالحل: {row['الحل']}"
    #         documents.append(content)
    #         metadatas.append({
    #             "القطعة المرشحة": str(row['قطعة الغيار المرشحة']),
    #             "الفئة": str(row['الفئة']),
    #             "الحل المقترح": str(row['الحل']),
    #             "مستوى الصعوبة": str(row['مستوى الصعوبة'])
    #         })
    #         ids.append(f"id_{index}")
    #
    #     # تقسيم الـ 50 ألف سجل لمجموعات كل مجموعة 5000 سجل
    #     batch_size = 5000
    #     for i in range(0, len(documents), batch_size):
    #         self.collection.add(
    #             documents=documents[i : i + batch_size],
    #             metadatas=metadatas[i : i + batch_size],
    #             ids=ids[i : i + batch_size]
    #         )
    #         print(f"تم رفع الدفعة رقم {i//batch_size + 1} بنجاح...")
    #
    #     print(f"Successfully ingested {len(documents)} documents.")
    #
    # def ingest_google_sheets(self):
    #     try:
    #         # 1. استخدام طريقتك الممتازة لبناء الرابط
    #         SHEET_ID = "1fYl8z6CoUOBbQNlVffoLNeB5cJ6nD-ombv2yHkDNFlc"
    #         SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?usp=sharing"
    #
    #         #https://docs.google.com/spreadsheets/d/1fYl8z6CoUOBbQNlVffoLNeB5cJ6nD-ombv2yHkDNFlc/edit?usp=sharing
    #
    #         # 2. قراءة البيانات مباشرة باستخدام Pandas
    #         df = pd.read_csv(SHEET_URL)
    #
    #         # 3. تنظيف البيانات (حذف أي صفوف فارغة تماماً)
    #         df = df.dropna(how='all')
    #
    #         # 4. تحضير القوائم لإدخالها في قاعدة البيانات (ChromaDB مثلاً)
    #         documents = []
    #         metadatas = []
    #         ids = []
    #
    #         for index, row in df.iterrows():
    #             # تجهيز النص الذي سيبحث فيه الذكاء الاصطناعي
    #             content = f"{row.get('المشكلة', '')} {row.get('الحل المقترح', '')}"
    #             documents.append(content)
    #
    #             # تخزين باقي الأعمدة كـ Metadata لاسترجاعها لاحقاً
    #             # نحول أي قيم NaN إلى None عشان ميعملش مشكلة مع قاعدة البيانات
    #             row_dict = row.where(pd.notnull(row), None).to_dict()
    #             metadatas.append(row_dict)
    #             ids.append(str(index))
    #
    #         # 5. إضافة البيانات
    #         self.collection.add(
    #             documents=documents,
    #             metadatas=metadatas,
    #             ids=ids
    #         )
    #         print(f"✅ تم سحب {len(df)} صف من جوجل شيت بنجاح!")
    #
    #     except Exception as e:
    #         print(f"❌ حدث خطأ أثناء سحب البيانات: {e}")

    def search(self, query: str, n_results: int = 3):
        results = self.collection.query(query_texts=[query], n_results=n_results)
        return results
