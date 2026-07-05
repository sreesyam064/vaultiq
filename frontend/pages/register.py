import streamlit as st
from utils.api import register_user

st.set_page_config(
    page_title="VaultIQ — Register",
    page_icon="🧠",
    layout="centered"
)

st.title("VaultIQ")
st.caption("Your Personal Knowledge Base Assistant")

st.subheader("Create your account")

username = st.text_input("Username")
email = st.text_input("Email")
password = st.text_input("Password", type="password")
confirm_password = st.text_input("Confirm Password", type="password")

if st.button("Register", use_container_width=True):
    if not username or not email or not password:
        st.error("All fields are required")
    elif password != confirm_password:
        st.error("Passwords do not match.")
    else:
        try:
            register_user(username, email, password)
            st.success("Registration successful! Please login.")
            st.switch_page("app.py")
        except Exception as e:
            st.error(f"Registration failed: {e}")
    
st.divider()

st.write("Already have an account?")
if st.button("Login", use_container_width=True):
    st.switch_page("app.py")