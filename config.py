import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY not found. Add it in .env file.")

MODEL_NAME = "llama-3.3-70b-versatile"

DB_PATH = Path("database/sales_poc.db")