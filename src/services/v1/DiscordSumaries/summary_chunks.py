from sqlalchemy.orm import Session
from src import discord_models as models
from datetime import datetime
from langchain_core.language_models.chat_models import BaseChatModel
from .prompts import SUMMARY_DISCORD_MESSAGES_2
from .format_db_messages import format_db_messageses

from sqlalchemy.orm import Session
from typing import List, TypedDict, Dict, Any
import asyncio


from src.logging_config import get_logger
logger = get_logger(module_name="summary_chunks", DIR="DiscordSumaries")






class ProccesSingleChunk(TypedDict):
    summary : str
    usage_metadata : Dict[str, Any]
    idx : int
    llm_model : str


async def process_single_chunk(llm : BaseChatModel, llm_model : str, prompt : str, idx : int, semaphore : asyncio.Semaphore) -> ProccesSingleChunk:
    #print("\n")
    #print("****** precess_single_chunk")
    async with semaphore:
        try:
            ai_message = await llm.ainvoke(prompt)
            #print(f"usage_metadata: {ai_message.usage_metadata}, \n\n numero de caracteres: {len(ai_message.content)} \n\n\n")
            logger.info(f"input tokens: {ai_message.usage_metadata.get("input_tokens")} | output tokens: {ai_message.usage_metadata.get("output_tokens")}")
            return {"summary": ai_message.content, "usage_metadata":ai_message.usage_metadata, "idx":idx, "llm_model":llm_model}
        except Exception as e:
            logger.error(f"error procesando en el registro {idx} de DiscordChannelChronologicalSummary: \n {e} \n\n")
            return None





def collect_all_pending_summaries(session: Session) -> List[str]:
    logger.info("collect_all_pending_summaries")
    """
    Recorre la jerarquía y devuelve una lista plana de todos los prompts pendientes.
    Esto evita procesar canal por canal y permite paralelismo real.
    """
    all_tasks = []

    # 1. Obtener registros pendientes del canal actual
    summary_records = session.query(models.DiscordChannelChronologicalSummary).filter(
        models.DiscordChannelChronologicalSummary.summary.is_(None),
    ).order_by(models.DiscordChannelChronologicalSummary.start_time).all()

    if summary_records is None:
        logger.warning("summary_records es vacio")
        return None
    
    logger.info(f"Hay {len(summary_records)} registros en DiscordChannelChronologicalSummary que su status es None")

    for obj in summary_records:
        messages = format_db_messageses(session, channel_id=obj.channel_id, summary_from=obj.start_time, summary_end=obj.end_time)
        if messages:
            prompt = SUMMARY_DISCORD_MESSAGES_2.format(messages=messages)
            all_tasks.append({"prompt": prompt, "idx": obj.id})
        
    return all_tasks







async def make_all_pending_summaries(session : Session, semaphore : asyncio.Semaphore, llm : BaseChatModel, llm_model : str):
    logger.info("make_all_pending_summaries")
    prompts = collect_all_pending_summaries(session=session)

    if prompts is None:
        logger.warning("prompts es vacio")
        return None
    
    logger.info("Prompts conseguidos")
    
    tasks = [
        process_single_chunk(
            llm=llm,
            llm_model=llm_model,
            prompt=p["prompt"],
            idx=p["idx"],
            semaphore=semaphore,
        ) for p in prompts
    ]
    logger.info("tasks conseguidos")

    # result : List[ProccesSingleChunk] = await asyncio.gather(*tasks)
    # total_tasks = len(result)
    total_tasks = len(tasks)

    count = 0
    input_tokens, output_tokens = 0, 0

    for task in asyncio.as_completed(tasks):
        result = await task

        if result and result["summary"]:
            result : ProccesSingleChunk

            llm_model = result.get("llm_model")

            db_record = session.query(models.DiscordChannelChronologicalSummary).filter_by(id=result["idx"]).first()
            

            if db_record:
                db_record.summary = result["summary"]
                db_record.model = llm_model
                
                logger.info(f"guardando summary con id {db_record.id} ")

                meta = result.get("usage_metadata")
                if meta:
                    input_tokens += meta.get("input_tokens", 0)
                    output_tokens += meta.get("output_tokens", 0)

                    db_record.input_tokens = meta.get("input_tokens", 0)
                    db_record.output_tokens = meta.get("output_tokens", 0)
                    db_record.model = llm_model

                session.add(db_record)
                session.commit()

                count += 1
                logger.info(f"--- [Progreso: {count}/{total_tasks}] Registro {result['idx']} guardado correctamente.")

    
    logger.info(f"\n--- ✨ ¡PROCESO FINALIZADO!")
    logger.info(f"--- 📊 Resúmenes guardados: {count}")
    logger.info(f"--- 📊 Tokens totales: In: {input_tokens} | Out: {output_tokens}")



if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from langchain_deepseek import ChatDeepSeek
    from src.logging_config import setup_base_logging
    from src import settings
    import asyncio

    setup_base_logging()

    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING)
    MySession = sessionmaker(bind=engine)
    session = MySession()

    semaphore = asyncio.Semaphore(4)
    
    model = "deepseek-v4-flash"
    llm = ChatDeepSeek(model=model, temperature=0.3, api_key=settings.DEEPSEEK_API_KEY)


    asyncio.run(
        make_all_pending_summaries(session=session,semaphore=semaphore, llm=llm, llm_model=model)
    )

    


"""
python3 -m src.services.v1.DiscordSumaries.summary_chunks


"""
