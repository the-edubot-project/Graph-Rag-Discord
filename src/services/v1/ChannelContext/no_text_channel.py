from src import discord_models as models
from .prompt import SUMMARY_FORUM_OR_CATEGORY_CHANNEL_PROMPT_3

from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy.orm import Session
from typing import TypedDict, List, Dict, Any


from src.logging_config import get_logger
logger = get_logger(module_name="summary_text", DIR="ChannelSummary_v2")



def summary_foroum_or_category(session : Session, llm :BaseChatModel, root_id : int):
    
    channel = session.query(models.DiscordChannel).filter_by(id=root_id).first()

    if channel is None:
        logger.error(f"El canal con id {root_id} No existe")
        return None

    records = session.query(
        models.DiscordChannel.name,
        models.DiscordChannelContext.summary_context
    ).join(
        models.DiscordChannelContext,
        models.DiscordChannel.id == models.DiscordChannelContext.channel_id
    ).filter(
        models.DiscordChannel.parent_channel_id == root_id,
    ).all()

    logger.info(f"Hay {len(records)} canales de texto en el foro/categoria {root_id}")
    if len(records) == 0:
        print(f"hay 0 canales en este foro o categoria, saltando ...")
        return 
    channels_summaries = []
    for r in records:
        channel_name = r[0]
        summary_context = r[1]
        text = f"# Resumen del canala {channel_name} \n\n {summary_context} \n\n --- \n"
        channels_summaries.append(text)
    
    channels_summaries = "\n\n".join(channels_summaries)

    prompt = SUMMARY_FORUM_OR_CATEGORY_CHANNEL_PROMPT_3.format(discord_channel=channel.name, channels_summaries=channels_summaries)

    ai_message = llm.invoke(prompt)
    if ai_message.content is None:
        logger.error("Warning el llm respondió None")
        return None
    print(f"usage_metadata {ai_message.usage_metadata}")

    new_record = models.DiscordChannelContext(channel_id=root_id, summary_context=ai_message.content)
    session.add(new_record)
    session.commit()
    # session.close()
    



if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from langchain_google_genai import ChatGoogleGenerativeAI
    from src import settings

    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING)
    MySession = sessionmaker(bind=engine)
    session = MySession()

    # model = "gemini-3-flash-preview"
    model = "gemini-2.5-flash"
    llm = ChatGoogleGenerativeAI(model=model, temperature=0.4, api_key=settings.GOOGLE_API_KEY)

    # root_id = 1309953285582491649  #  📐 Validation + Engineering
    root_id = 1311706520467144808 # foro solenium

    summary_foroum_or_category(session=session, llm=llm, root_id=root_id)





"""
python3 -m src.services.v1.DiscordGraph.DiscordContexChannnels.no_text_channel


"""
