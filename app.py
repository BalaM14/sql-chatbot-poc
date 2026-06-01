import streamlit as st

from Chatbot import ask_sql_bot


st.set_page_config(
    page_title="SQL Chatbot POC",
    page_icon="🤖",
    layout="wide"
)

st.title("SQL Chatbot POC")
st.write("Ask questions in natural language. The bot converts them into SQL and fetches results from the existing database.")

user_question = st.text_input(
    "Ask your question",
    placeholder="Example: Show top 5 products by total sales"
)

if st.button("Ask"):
    if not user_question.strip():
        st.warning("Please enter a question.")
    else:
        with st.spinner("Generating SQL and fetching data..."):
            df, generated_sql, status, rewritten_request = ask_sql_bot(user_question)

        st.subheader("Interpreted Question")
        st.write(rewritten_request) 

        st.subheader("Generated SQL")
        st.code(generated_sql, language="sql")

        if status == "success":
            st.subheader("Result")
            st.dataframe(df, width='stretch')
        else:
            st.error(status)