"""
Modelo de la tabla de logs persistidos en Postgres: `graph_rag_discord_logs`.

Vive en su propio módulo (y con su propia Base declarativa, igual que
src/lightrag_models.py) para que el logging no dependa de src/discord_models.py:
así src/logging_config.py puede importarlo sin arrastrar pgvector ni el resto del
esquema de Discord.

Campos:
  - level        nivel del registro: 'INFO' | 'WARNING' | 'ERROR'.
  - content      contenido del mensaje (con traceback si el log traía exc_info).
  - script_path  ruta del script que emitió el log, relativa a la raíz del repo
                 (p.ej. 'src/services/v1/DiscordSumaries/chunking.py').
  - inserted_at  fecha/hora de inserción del registro (default de la BD).

Quien escribe aquí es PostgresLogHandler (src/logging_config.py), enganchado a los
loggers de los servicios DiscordSumaries y NaiveRag vía get_logger(..., to_db=True).

DDL: migrations/2026-07-28_graph_rag_discord_logs.sql
"""

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    func,
)


class LogBase(DeclarativeBase):
    pass


# Valores permitidos en la columna `level`.
LEVEL_INFO = "INFO"
LEVEL_WARNING = "WARNING"
LEVEL_ERROR = "ERROR"
LOG_LEVELS = (LEVEL_INFO, LEVEL_WARNING, LEVEL_ERROR)


class GraphRagDiscordLog(LogBase):
    __tablename__ = "graph_rag_discord_logs"

    id = Column(Integer, primary_key=True)
    level = Column(String(16), nullable=False, index=True)
    content = Column(Text, nullable=False)
    script_path = Column(Text, index=True)
    inserted_at = Column(DateTime, server_default=func.now(), index=True)

    def __repr__(self) -> str:  # pragma: no cover - ayuda en consola/depuración
        return (
            f"<GraphRagDiscordLog id={self.id} level={self.level!r} "
            f"script_path={self.script_path!r}>"
        )
