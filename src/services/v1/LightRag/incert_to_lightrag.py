
from sqlalchemy.orm import Session
from . import lightrag_helper as lightrag
from .get_lightrag_vllm_googleEmb import _get_rag
from src.logging_config import get_logger
from src import discord_models as dmodels

logger = get_logger(module_name="a", DIR="A")



async def main_pipeline(session : Session):

    lightrag.mark_ready_for_lightrag(session=session)

    records = session.query(
        dmodels.DiscordChannelChronologicalSummary.id,
        dmodels.DiscordChannelChronologicalSummary.channel_id,
        dmodels.DiscordChannelChronologicalSummary.start_time,
        dmodels.DiscordChannelChronologicalSummary.end_time,
        dmodels.DiscordChannelChronologicalSummary.summary
    ).join(
        dmodels.DiscordSummaryStatus,
        dmodels.DiscordSummaryStatus.summary_id == dmodels.DiscordChannelChronologicalSummary.id
    ).filter(
        dmodels.DiscordSummaryStatus.lightrag_status == "ready"
    ).all()

    for r in records:
        await lightrag.insert_to_light_rag(
            session=session,
            lightrag=_get_rag(),
            summary_id=r.summary_id,
            channel_id=r.channel_id,
            start_time=r.start_time,
            end_time=r.end_time,
            summary=r.summary
        )



if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src import settings
    import asyncio

    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING)
    MySession = sessionmaker(bind=engine)
    session = MySession()

    asyncio.run(
        main_pipeline(session=session)
    )

    
