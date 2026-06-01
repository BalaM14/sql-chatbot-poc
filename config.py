import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

try:
    import streamlit as st

    GROQ_API_KEY = st.secrets.get("GROQ_API_KEY")

except Exception:
    GROQ_API_KEY = None

if not GROQ_API_KEY:
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise ValueError(
        "GROQ_API_KEY not found in Streamlit Secrets or environment variables."
    )

MODEL_NAME = "llama-3.1-8b-instant"

DB_PATH = Path("database/sales_poc.db")