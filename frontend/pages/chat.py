import streamlit as st

from components.initialize_chat import initialize_chat
from components.sidebar import show_sidebar
from components.messages import show_messages
from components.question_input import handle_question
from components.welcome import show_welcome_screen

st.set_page_config(
    page_title="VaultIQ — Chat",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Authentication check
if "token" not in st.session_state:
    st.switch_page("app.py")
    
# Initialize session
initialize_chat()

# Sidebar
show_sidebar()

if len(st.session_state.messages) == 0:
    show_welcome_screen()
    
# Display chat history
show_messages()

# Handle new question (typed or suggested)
handle_question()