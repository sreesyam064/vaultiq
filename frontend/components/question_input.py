import streamlit as st

from utils.api import ask_question

def handle_question():       
    # User types a question
    question = st.chat_input("Ask VaultIQ anything about your documents...")
    
    # Suggested question from welcome screen    
    if question is None and "suggested_question" in st.session_state:
        question = st.session_state.pop("suggested_question")
    
    if not question:
        return
    
    # 1. Save user message
    st.session_state.messages.append({"role": "user", "content": question})

    # 2. Call API
    with st.spinner("VaultIQ is thinking..."):
        try:
            result = ask_question(
                st.session_state["token"],
                st.session_state["session_id"],
                question
            )
            
            answer = result.get("answer", "")
            sources = result.get("sources", [])
            
            full_response = answer
            if sources:
                full_response += "\n\n#### Sources\n"
                for source in sources:
                    full_response += f"- {source}\n"
                    
            # 3. Save assistant message
            st.session_state.messages.append({
                "role": "assistant",
                "content": full_response
            })
            
        except Exception as e:
            st.session_state.messages.pop()
            st.error(f"Failes to get response from VaultIQ: {e}")
            return 
    
    # 4. Rerun — show_messages() renders the full updated history cleanly
    st.rerun()
    