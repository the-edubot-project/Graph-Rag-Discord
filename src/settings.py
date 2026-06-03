from sqlalchemy import URL
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")

DB_NAME = os.getenv("DB_NAME")


THE_EDUBOT_PROJECT_DB_CONN_STRING = URL.create(
    drivername="postgresql+psycopg2",
    username=DB_USER,
    password=DB_PASS,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME
)


USELSESS_CHANNELS = [1420410366545887322, 1321152642130513971]   








# 1374752699123240960 insumosbot  1321152642130513971 

# ============================ Por deprecar ? ============================

DB_NAME_DISCORD = os.getenv("DB_NAME_DISCORD")
DB_NAME_LIGHTRAG = os.getenv("DB_NAME_LIGHTRAG")
DB_NAME_EDUCHAT = os.getenv("DB_NAME_EDUCHAT")

DB_DISCORD_CONN_STRING = f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME_DISCORD}"
LIGHTRAG_CONN_STRING = f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME_LIGHTRAG}"


NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
