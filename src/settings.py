from sqlalchemy import URL
from pathlib import Path
from dotenv import load_dotenv
import logging
import os

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")

DB_NAME = os.getenv("DB_NAME")


THE_EDUBOT_DB_CONN_STRING = URL.create(
    drivername="postgresql+psycopg2",
    username=DB_USER,
    password=DB_PASS,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME
)


# ── Logs persistidos en la tabla graph_rag_discord_logs (src/log_models.py) ──
# DB_LOG_ENABLED=false apaga la escritura en BD (los logs siguen en fichero/consola).
# DB_LOG_LEVEL: nivel mínimo que se persiste (INFO | WARNING | ERROR).
DB_LOG_ENABLED = os.getenv("DB_LOG_ENABLED", "true").strip().lower() not in (
    "0", "false", "no", "off",
)
DB_LOG_LEVEL = getattr(
    logging, os.getenv("DB_LOG_LEVEL", "INFO").strip().upper(), logging.INFO
)


NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")



VLLM_BASE_URL = os.getenv("VLLM_BASE_URL")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")





