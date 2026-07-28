
from langchain_core.language_models.chat_models import BaseChatModel
from src import discord_models as models
from .text_channels import procces_all_peding_text_channel_summaries
from.no_text_channel import summary_foroum_or_category
from sqlalchemy.orm import Session
import asyncio


async def summary_text_channels(session : Session, semapfhore : asyncio.Semaphore, llm : BaseChatModel):
    roots = session.query(models.DiscordChannel).filter(
        models.DiscordChannel.parent_channel_id.is_(None)
    ).all()
    print(f"Hay {len(roots)} raices")
    
    for obj in roots:
        print(f"procesando el nodo {obj.id} channel name: {obj.name}")
        print("\n"*5)
        await procces_all_peding_text_channel_summaries(session=session, semaphore=semapfhore, llm=llm, root_id=obj.id)




def summary_no_text_chanels(session : Session, llm : BaseChatModel):
    all_forums_categories = session.query(models.DiscordChannel).filter(
        models.DiscordChannel.channel_type.in_({'category', 'forum'})
    ).all()
    print(f"hay {len(all_forums_categories)} foros o categorias")

    for obj in all_forums_categories:
        record = session.query(models.DiscordChannelContext).filter_by(channel_id=obj.id).first()
        if record:
            print(f"Ya se tiene el contexto del foro/categoria {obj.name} pasando al siguiente")
            continue
        print(f"Consiguiendo el contexto de {obj.name} con channel_id {obj.id}")
        summary_foroum_or_category(session=session, llm=llm, root_id=obj.id)
        






if __name__ == "__main__":

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_openai import ChatOpenAI
    from src import settings
    import asyncio

    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING)
    MySession = sessionmaker(bind=engine)
    session = MySession()

    semophare = asyncio.Semaphore(3)

    model = "gemma-4-26b"
    llm = ChatOpenAI(
    model=model,
    base_url=settings.VLLM_BASE_URL,
    api_key="EMPTY",
    temperature=0.2,
    max_tokens=8192,
    )


    # model = "gemini-2.5-flash"
    # llm = ChatGoogleGenerativeAI(model=model, temperature=0.4, api_key=settings.GOOGLE_API_KEY)


    try:
        asyncio.run(
            summary_text_channels(session=session, semapfhore=semophare, llm=llm)
        )
    finally:
        session.close()

    # summary_no_text_chanels(session=session, llm=llm)
    


"""
python3 -m src.services.v1.ChannelContext.main


"""