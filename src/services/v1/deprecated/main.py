from sqlalchemy.orm import Session
from sqlalchemy.engine import Engine

from .lightrag_crud import delete_in_lightrag_status, insert_to_light_rag, sweep_pending_deletions, get_pending_track_ids, sync_processed_lightrag_docs
from .summary_chunks import make_all_pending_summaries
from src import discord_models as dmodels

from langchain_core.language_models.chat_models import BaseChatModel

import asyncio
import time


async def prune_in_lightrag_status_from_summaries(session: Session):
    summary_records = session.query(dmodels.DiscordChannelChronologicalSummary).filter(
        dmodels.DiscordChannelChronologicalSummary.status == "in_lightrag",
        dmodels.DiscordChannelChronologicalSummary.summary.is_(None),
    ).all()

    if not summary_records:
        print("No hay registros en summary_records")
        return None

    print(f"Hay {len(summary_records)} registros para borrrar en el servicio de lightrag")

    summary_ids = []
    for obj in summary_records:
        summary_ids.append(obj.id)

    await delete_in_lightrag_status(session=session, summary_ids=summary_ids)




def partition_summary(session: Session, max_msg: int = 10000):
    summary_records = session.query(dmodels.DiscordChannelChronologicalSummary).filter(
        dmodels.DiscordChannelChronologicalSummary.status == None
    ).all()

    if not summary_records:
        print("summary_records es None")
        return None

    for obj in summary_records:
        if obj.number_messages >= max_msg:
            print(f"Particionando summary con id {obj.id} del canal con id {obj.channel_id}")
            messages_records = session.query(dmodels.DiscordMessage).filter(
                dmodels.DiscordMessage.channel_id == obj.channel_id,
                dmodels.DiscordMessage.message_create_at >= obj.start_time,
                dmodels.DiscordMessage.message_create_at <= obj.end_time,
            ).order_by(dmodels.DiscordMessage.message_create_at).all()

            if len(messages_records) < 2:
                print("messages_records < 2 saltando")
                continue

            mid = len(messages_records) // 2
            first_half = messages_records[:mid]
            second_half = messages_records[mid:]

            obj.end_time = first_half[-1].message_create_at
            obj.number_messages = len(first_half)

            new_summary = dmodels.DiscordChannelChronologicalSummary(
                channel_id=obj.channel_id,
                start_time=second_half[0].message_create_at,
                end_time=second_half[-1].message_create_at,
                number_messages=len(second_half),
                status=None,
            )
            session.add(new_summary)

    session.commit()




async def main():
    pass



if __name__ == "__main__":
    from .chunking_messages import chunking_recursively_by_channel_id
    from . import conf

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src import settings
    import asyncio

    engine = create_engine(settings.DB_DISCORD_CONN_STRING)
    MySession = sessionmaker(bind=engine)
    session = MySession()
    
    # Paso #1 chunkenizar los nuevos mensajes de discord

    # for root in conf.ROOT_IDS:
    #     chunking_recursively_by_channel_id(engine=engine, session=session, channel_id=root)


    #Paso 2
    asyncio.run(
        prune_in_lightrag_status_from_summaries(session=session)
    )
    





"""
python3 -m src.services.v1.LightRag.main


"""