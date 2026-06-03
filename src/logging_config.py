from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import shutil
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


def get_logger(module_name: str, DIR : str):
    """
    Crea (si no existe) y retorna un logger específico para un módulo dentro de myGraphs.
    Ejemplo: get_logger("graph1")
    """

    LOG_DIR = settings.ROOT / ".logs2" / f"{DIR}"
    LOG_DIR.mkdir(parents=True, exist_ok=True)   

    log_path = LOG_DIR / f"{module_name}.log"
    logger = logging.getLogger(module_name)
    logger.setLevel(logging.DEBUG)

    # evitar duplicados
    if logger.handlers:
        return logger

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

    return logger

