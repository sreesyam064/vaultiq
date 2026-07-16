import streamlit as st
from utils.api import upload_documents

st.set_page_config(
    page_title="VaultIQ — Upload",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed"
)

if "token" not in st.session_state:
    st.switch_page("app.py")
    
st.title("VaultIQ")    
st.subheader("Upload Documents")
st.caption("Upload PDFs to build your personal knowledge base.")

uploaded_files = st.file_uploader(
    "Choose PDF files",
    type=["pdf"],
    accept_multiple_files=True
)

if st.button("Upload", use_container_width=True):    
    if not uploaded_files:
        st.error("Please select at least one PDF.")
    else:
        try:    
            result = upload_documents(
                st.session_state["token"],
                uploaded_files
            )
            
            uploaded = result.get("uploaded", [])
            skipped = result.get("skipped", [])
            errors = result.get("errors", [])
            
            if uploaded:
                names = ", ".join(f["file"] for f in uploaded)
                st.success(f"Uploaded: {names}")
            
            if skipped:
                for item in skipped:
                    st.warning(f"'{item['file']}' was skipped — {item['reason']}")
            
            if errors:
                for item in errors:
                    st.error(f"'{item['file']}' failed — {item['reason']}")
                    
            if not uploaded and not skipped and not errors:
                st.info("No files were processed.")
                     
            if uploaded:
                st.switch_page("pages/chat.py")
    
        except Exception as e:
            st.error(f"Unable to connect to backend: {e}")
        
st.divider()        
            
if st.button("Skip for now — go to chat", use_container_width=True):
    st.switch_page("pages/chat.py")
                