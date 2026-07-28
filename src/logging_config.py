from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import shutil
import sys
import threading
from src import settings

def setup_base_logging():
    """Configura el logger base (root): consola + nivel DEBUG."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # evitar duplicados
    if root_logger.handlers:
        return

    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)

    root_logger.addHandler(console_handler)


# ──────────────────── persistencia de logs en Postgres ────────────────────
# Los logs de los servicios de producción (DiscordSumaries y NaiveRag) además de
# ir a fichero/consola se guardan en la tabla graph_rag_discord_logs
# (modelo: src/log_models.py). Se activa por logger con get_logger(..., to_db=True).

# Un solo engine para todo el logging, creado de forma perezosa y con su propio
# pool: así los INSERT de logs NUNCA comparten transacción con la Session del
# pipeline (un commit de log no debe arrastrar trabajo a medio hacer).
_log_engine = None
_log_engine_lock = threading.Lock()

# Los mensajes muy largos (prompts, dumps) se recortan para no inflar la tabla.
MAX_LOG_CONTENT_CHARS = 20000

# Tras este número de fallos consecutivos el handler se apaga solo (BD caída o
# tabla inexistente) para no frenar el pipeline ni inundar stderr.
MAX_CONSECUTIVE_DB_FAILURES = 3


def _get_log_engine():
    global _log_engine
    if _log_engine is None:
        with _log_engine_lock:
            if _log_engine is None:
                from sqlalchemy import create_engine

                _log_engine = create_engine(
                    settings.THE_EDUBOT_DB_CONN_STRING,
                    pool_pre_ping=True,
                    pool_size=1,
                    max_overflow=2,
                    pool_recycle=1800,
                )
    return _log_engine


def _level_name(levelno: int) -> str:
    """Colapsa el nivel de logging a los tres valores de la columna `level`."""
    if levelno >= logging.ERROR:      # ERROR y CRITICAL
        return "ERROR"
    if levelno >= logging.WARNING:
        return "WARNING"
    return "INFO"                     # INFO (y DEBUG, que normalmente no llega)


def _script_path(record: logging.LogRecord) -> str:
    """Ruta del script que emitió el log, relativa a la raíz del repo si se puede."""
    try:
        return str(Path(record.pathname).resolve().relative_to(settings.ROOT))
    except (ValueError, OSError):
        return record.pathname


class PostgresLogHandler(logging.Handler):
    """
    Handler que inserta cada registro en graph_rag_discord_logs.

    - Un INSERT por registro, en su propia transacción corta (engine dedicado).
    - Nunca propaga excepciones: si la BD falla, el log sigue yendo a fichero y
      consola. Tras MAX_CONSECUTIVE_DB_FAILURES fallos seguidos se desactiva.
    """

    def __init__(self, level: int = logging.INFO):
        super().__init__(level=level)
        # Solo el mensaje (Formatter.format ya le añade el traceback si hay exc_info).
        self.setFormatter(logging.Formatter("%(message)s"))
        self._failures = 0
        self._disabled = False

    def emit(self, record: logging.LogRecord) -> None:
        if self._disabled:
            return
        try:
            from sqlalchemy import insert

            from src.log_models import GraphRagDiscordLog

            content = self.format(record)
            if len(content) > MAX_LOG_CONTENT_CHARS:
                content = content[:MAX_LOG_CONTENT_CHARS] + " …[truncado]"

            stmt = insert(GraphRagDiscordLog.__table__).values(
                level=_level_name(record.levelno),
                content=content,
                script_path=_script_path(record),
            )
            with _get_log_engine().begin() as conn:
                conn.execute(stmt)

            self._failures = 0
        except Exception as exc:  # noqa: BLE001 - el logging jamás debe romper el proceso
            self._failures += 1
            if self._failures >= MAX_CONSECUTIVE_DB_FAILURES:
                self._disabled = True
                print(
                    f"[logging_config] PostgresLogHandler desactivado tras "
                    f"{self._failures} fallos consecutivos: {exc}",
                    file=sys.stderr,
                )


def get_logger(module_name: str, DIR : str, to_db: bool = False):
    """
    Crea (si no existe) y retorna un logger específico para un módulo dentro de myGraphs.
    Ejemplo: get_logger("graph1")

    to_db=True añade además persistencia en la tabla graph_rag_discord_logs
    (nivel settings.DB_LOG_LEVEL, INFO por defecto; se puede apagar del todo con
    DB_LOG_ENABLED=false).
    """

    LOG_DIR = settings.ROOT / ".logs2" / f"{DIR}"
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_path = LOG_DIR / f"{module_name}.log"
    logger = logging.getLogger(module_name)
    logger.setLevel(logging.DEBUG)

    # evitar duplicados (por tipo de handler: un mismo logger puede pedirse desde
    # varios módulos, unos con to_db y otros sin él)
    if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        file_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)

        logger.addHandler(file_handler)
        logger.propagate = True  # para que también salga a la consola del root

    if (
        to_db
        and settings.DB_LOG_ENABLED
        and not any(isinstance(h, PostgresLogHandler) for h in logger.handlers)
    ):
        logger.addHandler(PostgresLogHandler(level=settings.DB_LOG_LEVEL))

    return logger
