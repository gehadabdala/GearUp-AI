import streamlit as st
import requests
import json

# الرابط المحلي للسيرفر اللي إنتِ مشغلاه
API_URL = "http://127.0.0.1:8000/recommend"

st.set_page_config(page_title="GearUp AI", page_icon="🏎️")
st.title("🏎️ GearUp AI: مساعد الأعطال")

if "messages" not in st.session_state:
    st.session_state.messages = []

# عرض الشات
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# إدخال اليوزر
if prompt := st.chat_input("إيه المشكلة في عربيتك؟"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("بفكر في الحل... 🛠️"):
            try:
                # إرسال الطلب للسيرفر
                payload = {
                    "user_id": "1",
                    "query_data": json.dumps(
                        {"messages": [{"role": "user", "content": prompt}]}
                    ),
                }
                response = requests.post(API_URL, data=payload)

                if response.status_code == 200:
                    answer = response.json().get("ai_answer", "لا يوجد رد")
                    st.markdown(answer)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": answer}
                    )
                else:
                    st.error(f"خطأ في السيرفر: {response.status_code}")
            except Exception as e:
                st.error(f"تأكدي إن سيرفر الـ FastAPI شغال! {e}")
