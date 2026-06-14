"""
Pipeline principal del servicio Graphiti: procesa los resúmenes de
discord_chronological_summary marcados como 'ready' y los ingiere en el grafo
de conocimiento temporal de Graphiti.

Análogo a LightRag/incert_to_lightrag.py.
"""

from sqlalchemy.orm import Session

from src.logging_config import get_logger
from src import discord_models as dmodels
from . import graphiti_helper as gh
from .get_graphiti_vllm_googleEmb import _get_graphiti

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

        logger.info("Ingiriendo %d resúmenes en Graphiti", len(records))

        for r in records:
            await gh.insert_to_graphiti(
                graphiti=graphiti,
                session=session,
                summary_id=r.summary_id,
                channel_id=r.channel_id,
                start_time=r.start_time,
                end_time=r.end_time,
                summary=r.summary,
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
