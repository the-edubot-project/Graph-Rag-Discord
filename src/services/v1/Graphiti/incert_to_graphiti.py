"""
Pipeline principal del servicio Graphiti: procesa los resúmenes de
discord_chronological_summary marcados como 'ready' y los ingiere en el grafo
de conocimiento temporal de Graphiti.

Análogo a LightRag/incert_to_lightrag.py.
"""

from sqlalchemy.orm import Session

from src.logging_config import get_logger, setup_base_logging
from src import discord_models as dmodels
from . import graphiti_helper as gh
from .get_graphiti_vllm_googleEmb import _get_graphiti

# Activa el handler de consola del root para que los logs salgan también en
# pantalla (get_logger propaga al root, pero el root no tiene consola hasta que
# se llama a esto).
setup_base_logging()

logger = get_logger(module_name="incert_to_graphiti", DIR="Graphiti")


async def main_pipeline(session: Session):
    graphiti = await _get_graphiti()

    try:
        # 1) marca como 'ready' los resúmenes inmutables aún no procesados.
        gh.mark_ready_for_graphiti(session=session)

        # 2) recupera los resúmenes listos para ingerir.
        records = (
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
            # Orden cronológico: la extracción temporal mejora si los episodios
            # entran en orden (cada uno ve los previos del canal).
            .order_by(dmodels.DiscordChannelChronologicalSummary.start_time.asc())
            .all()
        )

        if not records:
            logger.info("No hay resúmenes 'ready' para ingerir en Graphiti")
            return

        total = len(records)
        logger.info("Ingiriendo %d resúmenes en Graphiti", total)

        ok, fallidos = 0, []
        for i, r in enumerate(records, start=1):
            logger.info(
                "[%d/%d] Procesando chunk summary_id=%s (canal=%s, start=%s)",
                i, total, r.summary_id, r.channel_id, r.start_time,
            )
            try:
                await gh.insert_to_graphiti(
                    graphiti=graphiti,
                    session=session,
                    summary_id=r.summary_id,
                    channel_id=r.channel_id,
                    start_time=r.start_time,
                    end_time=r.end_time,
                    summary=r.summary,
                )
                ok += 1
                logger.info("[%d/%d] Listo chunk summary_id=%s", i, total, r.summary_id)
            except Exception:
                # Deja la sesión usable tras el fallo. El chunk queda en estado
                # 'ready' (no se marcó 'in_graphiti'), así que se reintenta en la
                # próxima ejecución. Registramos el traceback y seguimos.
                session.rollback()
                fallidos.append(r.summary_id)
                logger.exception(
                    "[%d/%d] FALLÓ chunk summary_id=%s; se omite y continúa",
                    i, total, r.summary_id,
                )

        logger.info(
            "Ingesta terminada: %d ok, %d fallidos de %d. Fallidos: %s",
            ok, len(fallidos), total, fallidos,
        )

    finally:
        await graphiti.close()


if __name__ == "__main__":
    import asyncio
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src import settings

    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING)
    MySession = sessionmaker(bind=engine)
    session = MySession()

    asyncio.run(main_pipeline(session=session))


"""
python3 -m src.services.v1.Graphiti.incert_to_graphiti


"""