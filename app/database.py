import pandas as pd
import chromadb
from chromadb.utils import embedding_functions
from app.config import settings


class VectorDB:
    def __init__(self):
        # إعداد ChromaDB
        self.client = chromadb.Client()
        self.embedding_fn = embedding_functions.DefaultEmbeddingFunction()

        self.collection = self.client.get_or_create_collection(
            name="gearup_knowledge", embedding_function=self.embedding_fn
        )

    def ingest_data(self):
        """
        دالة موحدة لرفع البيانات من Google Sheets فقط
        مع منع التكرار + batching
        """

        # 1. منع التكرار
        if self.collection.count() > 0:
            print("✅ البيانات موجودة بالفعل في ChromaDB. تم تخطي مرحلة الرفع.")
            return

        try:
            # 2. التأكد من وجود مصدر البيانات
            if not settings.SHEET_ID:
                raise ValueError("❌ SHEET_ID غير موجود في environment variables")

            print("🌐 جاري سحب البيانات من Google Sheets...")

            df = pd.read_csv(settings.SHEET_URL)

            # 3. تنظيف البيانات
            df = df.dropna(how="all")
            df = df.fillna("")

            documents, metadatas, ids = [], [], []

            # 4. تجهيز البيانات
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
                difficulty = row.get("مستوى الصعوبة") or "متوسط"
                category = row.get("الفئة") or "عام"

                content = f"المشكلة: {problem}\nالوصف: {description}\nالحل: {solution}"
                documents.append(content)

                metadatas.append(
                    {
                        "القطعة المرشحة": str(part),
                        "الحل المقترح": str(solution),
                        "مستوى الصعوبة": str(difficulty).strip(),
                        "الفئة": str(category),
                    }
                )

                ids.append(f"id_{index}")

            # 5. batching
            batch_size = 5000

            for i in range(0, len(documents), batch_size):
                self.collection.add(
                    documents=documents[i : i + batch_size],
                    metadatas=metadatas[i : i + batch_size],
                    ids=ids[i : i + batch_size],
                )
                print(f"⏳ تم رفع الدفعة رقم {i // batch_size + 1} بنجاح...")

            print(f"✅ تم الانتهاء! إجمالي السجلات: {len(documents)}")

        except Exception as e:
            print(f"❌ خطأ أثناء ingest: {str(e)}")

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
