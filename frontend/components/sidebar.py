import streamlit as st

from utils.api import (
    create_session,
    get_sessions,
    load_chat
)

def show_sidebar():
    with st.sidebar:
        st.header("🧠 VaultIQ")
        st.caption("Personal Knowledge Base Assistant")
        
        
        username = st.session_state.get("username", "User")
        st.write(f"Welcome, **{username}**!")
        
        st.divider()
        
        if st.button("➕ New Chat", use_container_width=True):
            data = create_session(st.session_state["token"])            
            st.session_state.session_id = data["session_id"]
            st.session_state.messages = []
            st.rerun()
        
        if st.button("📁 Upload Documents", use_container_width=True):
            st.switch_page("pages/upload.py")
        
        st.divider()
        
        # Chat history
        sessions = get_sessions(st.session_state["token"])        
        st.subheader(f"History ({len(sessions)})")
        
        search_term = st.text_input("Search", placeholder="Search chats...")
        
        for session in sessions:    
            label = session["title"]
            
            if label is None:
                label = f"Chat {session['id']}"
                
            if len(label) > 35:
                label = label[:35] + "..."
                  
            if search_term and search_term.lower() not in label.lower():
                continue
                        
            # Mark current active session
            if session["id"] == st.session_state.get("session_id"):
                label = f"⭐ {label}"
            
            if st.button(label, key=f"session_{session['id']}", use_container_width=True): 
                
                history = load_chat(
                    st.session_state["token"],
                    session["id"]
                )    
                st.session_state.session_id = session["id"]
                st.session_state.messages = [
                    {
                        "role": message["role"],
                        "content": message["content"]
                    }
                    for message in history                     
                ]
                st.rerun()
                
        st.divider()

        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.clear()
            st.switch_page("app.py")
            