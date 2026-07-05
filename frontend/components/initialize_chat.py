import streamlit as st

from utils.api import create_session

def initialize_chat():
    
    if "messages" not in st.session_state:
        st.session_state.messages = []    

    if "session_id" not in st.session_state:
        try:
            data = create_session(
                st.session_state["token"]
            )
        
            st.session_state.session_id = data["session_id"]   
               
        except Exception as e:
            st.error(f"Failed to connect backend server: {e}")  
            st.stop()   
            
        