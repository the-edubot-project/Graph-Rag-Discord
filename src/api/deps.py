"""
Dependencias compartidas de la API (engine SQLAlchemy + sesión por request).

El engine y el sessionmaker se crean una sola vez al importar el módulo; cada
request obtiene una sesión propia que se cierra al terminar (patrón estándar de
FastAPI con `yield`).
"""

from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src import settings

engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Iterator[Session]:
    """Provee una sesión de SQLAlchemy por request y la cierra al finalizar."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
