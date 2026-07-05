import streamlit as st
        
def show_welcome_screen():
    st.markdown(
    """
    ## Welcome to 🧠 VaultIQ
    #### Your Personal Knowledge Base Assistant
    
    Upload your PDFs and ask questions about them in natural language.
    Ask your own question below or pick one of the suggestions to get started.
    """
    )
    
    st.divider()
    
    st.subheader("Suggested Questions")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button(
            "Summarize my documents",
            use_container_width=True
        ):
            st.session_state["suggested_question"] = "Summarize the uploaded documents."
            st.rerun()
        
        if st.button(
            "Compare topics",
            use_container_width=True
        ):
            st.session_state["suggested_question"] = "Compare the main topics discussed in the uploaded documents."
            st.rerun()    
     
    with col2:
        if st.button(
            "Explain important concepts",
            use_container_width=True
        ):
            st.session_state["suggested_question"] = "Explain the important concepts in the uploaded documents."
            st.rerun()
        
        if st.button(
            "Generate interview questions",
            use_container_width=True
        ):
            st.session_state["suggested_question"] = "Generate interview questions based on the uploaded documents."
            st.rerun()        
        
    st.divider()
    
    st.info("You can also type your own questions using chat box below.")