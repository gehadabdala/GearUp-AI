import pandas as pd
import chromadb
from chromadb.utils import embedding_functions
from app.config import settings

class VectorDB:
    def __init__(self):
        # إعداد ChromaDB
        self.client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=settings.EMBEDDING_MODEL
        )
        self.collection = self.client.get_or_create_collection(
            name="gearup_knowledge",
            embedding_function=self.embedding_fn
        )

    def ingest_excel(self):
        """رفع البيانات على دفعات لتجنب خطأ الـ Batch Size"""
        if self.collection.count() > 0:
            print("Data already ingested (ChromaDB contains data).")
            return

        df = pd.read_excel(settings.EXCEL_PATH)
        documents, metadatas, ids = [], [], []

        for index, row in df.iterrows():
            content = f"العطل: {row['العطل']}\nالوصف: {row['وصف العطل']}\nالحل: {row['الحل']}"
            documents.append(content)
            metadatas.append({
                "القطعة المرشحة": str(row['قطعة الغيار المرشحة']),
                "الفئة": str(row['الفئة']),
                "الحل المقترح": str(row['الحل']),
                "مستوى الصعوبة": str(row['مستوى الصعوبة'])
            })
            ids.append(f"id_{index}")

        # تقسيم الـ 50 ألف سجل لمجموعات كل مجموعة 5000 سجل
        batch_size = 5000
        for i in range(0, len(documents), batch_size):
            self.collection.add(
                documents=documents[i : i + batch_size],
                metadatas=metadatas[i : i + batch_size],
                ids=ids[i : i + batch_size]
            )
            print(f"تم رفع الدفعة رقم {i//batch_size + 1} بنجاح...")

        print(f"Successfully ingested {len(documents)} documents.")

    def search(self, query: str, n_results: int = 3):
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results
        )
        return results