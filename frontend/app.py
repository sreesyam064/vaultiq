import streamlit as st
from utils.api import login_user

st.set_page_config(
    page_title="VaultIQ — Login",
    page_icon="🧠",
    layout="centered"
)

st.title("🧠 VaultIQ")
st.caption("Your Personal Knowledge Base Assistant")

if  "token" in st.session_state:
    st.switch_page("pages/chat.py")

st.subheader("Login")

email = st.text_input("Email")
password = st.text_input("Password", type="password")

if st.button("Login", use_container_width=True):
    if not email or not password:
        st.error("Email and Password are required.")
    else:
        try:
            data = login_user(email, password)
            st.session_state["token"] = data["token"]
            st.session_state["user_id"] = data["user"]["id"]
            st.session_state["username"] = data["user"]["username"]
            st.switch_page("pages/upload.py")
        except Exception as e:
            st.error(f"Login failed: {e}")
    
st.divider()

st.write("Don't have an account?")
if st.button("Register", use_container_width=True):
    st.switch_page("pages/register.py")
        