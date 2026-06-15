"""
Scheduler del pipeline: ejecuta src.pipeline.run_pipeline todos los días a las
02:00 hora de Bogotá (America/Bogota).

Implementación sin dependencias externas: calcula con zoneinfo (stdlib) cuántos
segundos faltan para la próxima ejecución, duerme hasta entonces y corre el
pipeline. Pensado para correr como contenedor de larga vida (restart: always),
de modo que el cálculo de zona horaria es correcto aunque el host esté en UTC.
"""

import asyncio
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.logging_config import get_logger, setup_base_logging
from src.pipeline import run_pipeline

logger = get_logger(module_name="scheduler", DIR="pipeline")

TZ = ZoneInfo("America/Bogota")
RUN_HOUR = 2
RUN_MINUTE = 0


def _seconds_until_next_run() -> float:
    now = datetime.now(TZ)
    target = now.replace(hour=RUN_HOUR, minute=RUN_MINUTE, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def main() -> None:
    setup_base_logging()
    logger.info(
        "Scheduler iniciado. Pipeline diario a las %02d:%02d America/Bogota.",
        RUN_HOUR, RUN_MINUTE,
    )
    while True:
        wait = _seconds_until_next_run()
        next_run = datetime.now(TZ) + timedelta(seconds=wait)
        logger.info("Próxima ejecución: %s (en %.0f s)", next_run.isoformat(), wait)
        time.sleep(wait)

        try:
            logger.info("Lanzando pipeline programado…")
            asyncio.run(run_pipeline())
        except Exception:
            logger.exception("El pipeline programado falló; se reintentará mañana.")

        # Margen para no recalcular dentro del mismo minuto y re-disparar.
        time.sleep(60)


if __name__ == "__main__":
    main()
