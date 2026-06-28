
from sqlalchemy.orm import Session
from . import lightrag_helper as lightrag
from . import conf
from .get_lightrag_vllm_googleEmb import _get_rag, llm_tracker, embed_tracker
from src.logging_config import get_logger
from src import discord_models as dmodels

logger = get_logger(module_name="incert_to_lightrag", DIR="LightRag")


def _record_token_usage(session, summary_id, channel_id, llm_before, llm_after,
                        emb_before, emb_after):
    """Escribe dos filas (llm + embedding) con el delta de tokens consumido
    durante la inserción de este summary_id. Las llamadas servidas desde la
    caché de LightRAG aparecen como 0 (no consumen tokens nuevos)."""
    session.add(dmodels.LightragTokenUsage(
        summary_id=summary_id,
        channel_id=channel_id,
        kind="llm",
        model_name=conf.LLM_MODEL,
        input_tokens=llm_after["prompt_tokens"] - llm_before["prompt_tokens"],
        output_tokens=llm_after["completion_tokens"] - llm_before["completion_tokens"],
    ))
    session.add(dmodels.LightragTokenUsage(
        summary_id=summary_id,
        channel_id=channel_id,
        kind="embedding",
        model_name=conf.EMBED_MODEL,
        input_tokens=emb_after["prompt_tokens"] - emb_before["prompt_tokens"],
        output_tokens=0,
        embed_calls=emb_after["call_count"] - emb_before["call_count"],
    ))
    session.commit()



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

    lr = await _get_rag()

    for r in records:
        try:
            logger.info(f"procesando summary_id: {r.id}")

            llm_before = llm_tracker.get_usage()
            emb_before = embed_tracker.get_usage()

            await lightrag.insert_to_light_rag(
                session=session,
                lightrag=lr,
                summary_id=r.id,
                channel_id=r.channel_id,
                start_time=r.start_time,
                end_time=r.end_time,
                summary=r.summary
            )

            _record_token_usage(
                session, r.id, r.channel_id,
                llm_before, llm_tracker.get_usage(),
                emb_before, embed_tracker.get_usage(),
            )
        except Exception as e:
            logger.error(f"Error en el summary_id {r.id}: \n\n {e}")



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

    
"""
python3 -m src.services.v1.LightRag.incert_to_lightrag


"""