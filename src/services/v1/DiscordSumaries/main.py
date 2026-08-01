
if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.logging_config import setup_base_logging
    from langchain_deepseek import ChatDeepSeek
    from langchain_google_genai import ChatGoogleGenerativeAI

    from .chunking import rechunk_all_available_channels
    from .mark_mature import seed_mature_status
    from .summary_chunks import make_all_pending_summaries

    from src import settings
    import asyncio

    setup_base_logging()

    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING)
    MySession = sessionmaker(bind=engine)
    session = MySession()

    # Paso 1, se chunkenizan los mensjaes de discord_messages que no han sido chunkenizados
    rechunk_all_available_channels(session=session)

    # Paso 2. Segun la politica de chunkenizacion, un chunk puede 
    # llegar a un estado en el que ya permanece inmutable, 
    # despues de el paso anterior, se buscan los nuevos chunks que sean inmutables    
    seed_mature_status(session=session)


    # Paso 3, hacer los resumenes de los chunks
    # model = "deepseek-v4-flash"
    # llm = ChatDeepSeek(model=model, temperature=0.2, api_key=settings.DEEPSEEK_API_KEY)

    model = "gemini-2.5-flash"
    llm = ChatGoogleGenerativeAI(model=model, temperature=0.2, api_key=settings.GOOGLE_API_KEY)


    semaphore = asyncio.Semaphore(4)

    asyncio.run(
        make_all_pending_summaries(session=session, semaphore=semaphore, llm=llm, llm_model=model)
    )

    


