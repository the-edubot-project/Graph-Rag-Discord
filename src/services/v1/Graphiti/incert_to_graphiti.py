"""
Pipeline principal del servicio Graphiti: procesa los resúmenes de
discord_chronological_summary marcados como 'ready' y los ingiere en el grafo
de conocimiento temporal de Graphiti.

Análogo a LightRag/incert_to_lightrag.py.
"""

import asyncio
from collections import defaultdict

from sqlalchemy.orm import sessionmaker, Session

from src.logging_config import get_logger, setup_base_logging
from src import discord_models as dmodels
from . import graphiti_helper as gh
from . import conf
from .get_graphiti_vllm_googleEmb import _get_graphiti

# Activa el handler de consola del root para que los logs salgan también en
# pantalla (get_logger propaga al root, pero el root no tiene consola hasta que
# se llama a esto).
setup_base_logging()

logger = get_logger(module_name="incert_to_graphiti", DIR="Graphiti")


def _is_transient(exc: Exception) -> bool:
    """¿El error parece transitorio (merece reintento)?

    Cubre tanto google.genai (ServerError con .code) como openai (.status_code):
    503/429/5xx y errores de conexión/timeout. No reintenta 4xx no transitorios
    (p. ej. 400 de contexto excedido), que no se arreglarían reintentando.
    """
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if code in (408, 409, 429, 500, 502, 503, 504):
        return True
    return type(exc).__name__ in {
        "ServerError",            # google.genai (5xx)
        "RateLimitError",         # openai / genai
        "InternalServerError",    # openai
        "APITimeoutError",        # openai
        "APIConnectionError",     # openai
        "ServiceUnavailableError",
    }


async def _insert_with_retry(graphiti, session, **kwargs):
    """Inserta un episodio reintentando errores transitorios con backoff."""
    intentos = conf.MAX_RETRIES + 1
    for intento in range(1, intentos + 1):
        try:
            await gh.insert_to_graphiti(graphiti=graphiti, session=session, **kwargs)
            return
        except Exception as e:
            if intento < intentos and _is_transient(e):
                espera = conf.RETRY_BACKOFF * (2 ** (intento - 1))
                session.rollback()
                logger.warning(
                    "Error transitorio en summary_id=%s (%s: %s). "
                    "Reintento %d/%d en %.1fs",
                    kwargs.get("summary_id"), type(e).__name__, e,
                    intento, conf.MAX_RETRIES, espera,
                )
                await asyncio.sleep(espera)
                continue
            raise


def _fetch_ready_records(session : Session):
    """Marca los resúmenes maduros como 'ready' y devuelve los pendientes."""
    gh.mark_ready_for_graphiti(session=session)
    return (
        session.query(
            dmodels.DiscordChannelChronologicalSummary.id.label("summary_id"),
            dmodels.DiscordChannelChronologicalSummary.channel_id,
            dmodels.DiscordChannelChronologicalSummary.start_time,
            dmodels.DiscordChannelChronologicalSummary.end_time,
            dmodels.DiscordChannelChronologicalSummary.summary,
        )
        .join(
            dmodels.DiscordSummaryStatus,
            dmodels.DiscordSummaryStatus.summary_id
            == dmodels.DiscordChannelChronologicalSummary.id,
        )
        .filter(dmodels.DiscordSummaryStatus.graphiti_status == "ready")
        .order_by(dmodels.DiscordChannelChronologicalSummary.start_time.asc())
        .all()
    )


async def main_pipeline(session_factory: sessionmaker):
    """
    Ingiere los resúmenes 'ready' en Graphiti paralelizando ENTRE canales.

    - Cada worker procesa un canal completo en orden cronológico (secuencial),
      porque la dedup de Graphiti y previous_episode_uuids lo exigen.
    - Hasta conf.CONCURRENCY canales se procesan en paralelo.
    - Cada worker usa su PROPIA Session (las Session de SQLAlchemy no son
      seguras de compartir entre tareas async concurrentes).
    """
    graphiti = await _get_graphiti()

    try:
        # Fase de lectura (secuencial, una sola sesión).
        with session_factory() as session:
            records = _fetch_ready_records(session)

        if not records:
            logger.info("No hay resúmenes 'ready' para ingerir en Graphiti")
            return

        total = len(records)

        # Agrupa por canal preservando el orden cronológico (records ya viene
        # ordenado por start_time asc).
        por_canal: dict[int, list] = defaultdict(list)
        for r in records:
            por_canal[r.channel_id].append(r)

        logger.info(
            "Ingiriendo %d resúmenes de %d canales (concurrencia=%d)",
            total, len(por_canal), conf.CONCURRENCY,
        )

        cola: asyncio.Queue = asyncio.Queue()
        for item in por_canal.items():
            cola.put_nowait(item)

        # Contadores compartidos (asyncio es monohilo: seguro entre awaits).
        progreso = {"hechos": 0}
        ok_ids: list[int] = []
        fallidos: list[int] = []

        async def worker(worker_id: int):
            while True:
                try:
                    channel_id, items = cola.get_nowait()
                except asyncio.QueueEmpty:
                    return
                # Una sesión por canal/worker.
                with session_factory() as session:
                    for r in items:
                        progreso["hechos"] += 1
                        n = progreso["hechos"]
                        logger.info(
                            "[%d/%d] (w%d canal=%s) summary_id=%s start=%s",
                            n, total, worker_id, channel_id, r.summary_id, r.start_time,
                        )
                        try:
                            await _insert_with_retry(
                                graphiti,
                                session,
                                summary_id=r.summary_id,
                                channel_id=r.channel_id,
                                start_time=r.start_time,
                                end_time=r.end_time,
                                summary=r.summary,
                            )
                            ok_ids.append(r.summary_id)
                        except Exception:
                            # Agotados los reintentos (o error no transitorio).
                            # El chunk queda en 'ready' (no se marcó 'in_graphiti')
                            # -> se reintenta en la próxima ejecución.
                            session.rollback()
                            fallidos.append(r.summary_id)
                            logger.exception(
                                "[%d/%d] FALLÓ summary_id=%s; se omite y continúa",
                                n, total, r.summary_id,
                            )

        await asyncio.gather(
            *(worker(i) for i in range(conf.CONCURRENCY))
        )

        logger.info(
            "Ingesta terminada: %d ok, %d fallidos de %d. Fallidos: %s",
            len(ok_ids), len(fallidos), total, fallidos,
        )

    finally:
        await graphiti.close()


if __name__ == "__main__":
    from sqlalchemy import create_engine
    from src import settings

    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING)
    MySession = sessionmaker(bind=engine)

    asyncio.run(main_pipeline(session_factory=MySession))


"""
python3 -m src.services.v1.Graphiti.incert_to_graphiti


"""