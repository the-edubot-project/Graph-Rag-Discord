
from src import discord_models as models
from .prompt import SUMMARY_TEXT_CHANNEL_PROMPT_3

from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy.orm import Session
from typing import TypedDict, List, Dict, Any

import asyncio

from src.logging_config import get_logger
logger = get_logger(module_name="text_channels", DIR="DiscordContext")




def collect_all_chronological_summaries_by_channel(session : Session, channel_id : int):

    summary_records = session.query(models.DiscordChannelChronologicalSummary).filter(
        models.DiscordChannelChronologicalSummary.channel_id == channel_id,
        models.DiscordChannelChronologicalSummary.summary.is_not(None)
    ).order_by(models.DiscordChannelChronologicalSummary.start_time).all()

    if not summary_records:
        print(f"No hay resumenes del canal {channel_id}. Puede que el canal sea un foro o categoria o que no existan resumenes cronologicos del canal de texto o hilo")
        return
    
    cronological_summary_lenght = len(summary_records)

    template = "Resumen desde {start_time} hasta {end_time}. Resumen: \n\n {summary} \n\n --- \n\n\n\n\n"
    channel_summary = ""

    for obj in summary_records:
        channel_summary += template.format(
            start_time=obj.start_time.strftime("%d/%m/%Y %H:%M"),
            end_time=obj.end_time.strftime("%d/%m/%Y %H:%M"),
            summary=obj.summary
        )
    
    return {"channel_summary":channel_summary, "cronological_summary_lenght":cronological_summary_lenght}




class PendingSummaryPrompt(TypedDict):
    prompt : str
    cronological_summary_lenght : int
    channel_id : int
    

def collect_all_pending_channel_summaries_prompts(session : Session, root_id : int, processed_ids : set = None) -> List[PendingSummaryPrompt]:

    all_tasks = []

    # Canales que ya tienen un DiscordChannelContext generado: se saltan para no
    # duplicar registros ni volver a gastar llamadas al LLM. Se consulta una sola
    # vez en la llamada raiz y se propaga por la recursion.
    if processed_ids is None:
        processed_ids = {
            row[0] for row in session.query(models.DiscordChannelContext.channel_id).all()
        }

    channel_record = session.query(models.DiscordChannel).filter_by(id=root_id).first()
    if channel_record is None:
        print(f"el canal con id {root_id} no existe")
        return all_tasks

    channel_name = channel_record.name

    if channel_record.channel_type not in {"forum", "category"}:
        if root_id in processed_ids:
            print(f"El canal con id {root_id} ({channel_name}) ya tiene contexto, saltando ...")
        else:
            channel_dict = collect_all_chronological_summaries_by_channel(session=session, channel_id=root_id)
            if channel_dict is not None:
                channel_summary = channel_dict["channel_summary"]
                cronological_summary_lenght = channel_dict["cronological_summary_lenght"]
                prompt = SUMMARY_TEXT_CHANNEL_PROMPT_3.format(channel_name=channel_name, channel_summary=channel_summary)
                all_tasks.append({"prompt": prompt, "cronological_summary_lenght": cronological_summary_lenght, "channel_id": root_id})
    else:
        print(f"El canal con id {root_id} ({channel_name}) es una categoria o un foro, saltando pero explorando hijos ...")

    child_channels = session.query(models.DiscordChannel).filter(
        models.DiscordChannel.parent_channel_id == root_id
    ).all()

    for child in child_channels:
        child_tasks = collect_all_pending_channel_summaries_prompts(session=session, root_id=child.id, processed_ids=processed_ids)
        all_tasks.extend(child_tasks)

    return all_tasks




class ProcessResponse(TypedDict):
    usage_metadata : Dict[str, Any]
    summary : str
    idx : int
    cronological_summary_lenght : int

    pass

async def process_single_chunk(llm : BaseChatModel, semaphore : asyncio.Semaphore, pending_dict : PendingSummaryPrompt) -> ProcessResponse:
    print("\n")
    print("****** precess_single_chunk")
    async with semaphore:
        try:
            prompt = pending_dict.get("prompt")
            idx = pending_dict.get("channel_id")
            ai_message = await llm.ainvoke(prompt)
            content = ai_message.content
            if isinstance(content, list):
                content = "".join(block.get("text", "") for block in content if block.get("type") == "text")
            print(f"usage_metadata: {ai_message.usage_metadata}, \n\n numero de caracteres: {len(content)} \n\n\n")
            return {"summary": content, "usage_metadata":ai_message.usage_metadata, "idx":idx, "cronological_summary_lenght":pending_dict.get("cronological_summary_lenght")}
        except Exception as e:
            print(f"[ERROR] canal {idx}: {e}")
            logger.info(f"error procesando en el registro {idx} de DiscordChannelChronologicalSummary: \n {e} \n\n")
            return None





async def procces_all_peding_text_channel_summaries(session : Session, semaphore : asyncio.Semaphore, llm : BaseChatModel, root_id : int):
    pending_dicts = collect_all_pending_channel_summaries_prompts(session=session, root_id=root_id)

    if not pending_dicts:
        print(f"No hay tareas pendientes para el canal {root_id}")
        return

    tasks = [
        process_single_chunk(
            llm=llm, semaphore=semaphore, pending_dict=d
        )
        for d in pending_dicts
    ]
    
    result = await asyncio.gather(*tasks)

    input_tokens, output_tokens = 0, 0
    count = 0

    for r in result:
        if r is not None:
            record = models.DiscordChannelContext(
                channel_id=r.get("idx"),
                summary_context=r.get("summary"),
            )
            session.add(record)
            meta = r.get("usage_metadata")
            if meta:
                input_tokens += meta.get("input_tokens", 0)
                output_tokens += meta.get("output_tokens", 0)
            
            count += 1
    session.commit()

    print(f"\n--- ✨ ¡PROCESO FINALIZADO!")
    print(f"--- 📊 Resúmenes guardados: {count}")
    print(f"--- 📊 Tokens totales: In: {input_tokens} | Out: {output_tokens}")
            







def make_channel_summary(session : Session, channel_id :int, llm : BaseChatModel):

    chrnological_summary = collect_all_chronological_summaries_by_channel(session=session, channel_id=channel_id)

    channel_summary = chrnological_summary["channel_summary"]
    cronological_summary_lenght = chrnological_summary["cronological_summary_lenght"]

    channel = session.query(models.DiscordChannel).filter_by(id=channel_id).first()
    if channel is None:
        print(f"El canal con id {channel_id} No se encuentra")
    
    prompt = SUMMARY_TEXT_CHANNEL_PROMPT_3.format(
        channel_name=channel.name,
        channel_summary=channel_summary
    )

    ai_response = llm.invoke(prompt)

    print(f"usage_metadata: {ai_response.usage_metadata}")

    record = models.DiscordChannelContext(
        channel_id=channel_id,
        summary_context=ai_response.content,
    )

    session.add(record)
    session.commit()




if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from langchain_google_genai import ChatGoogleGenerativeAI
    from src import settings
    import asyncio

    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING)
    MySession = sessionmaker(bind=engine)
    session = MySession()

    semophare = asyncio.Semaphore(3)
    # model = "gemini-3-flash-preview"
    model = "gemini-2.5-flash"
    llm = ChatGoogleGenerativeAI(model=model, temperature=0.4, api_key=settings.GOOGLE_API_KEY)

    # root_id = 1309953285582491649 #  📐 Validation + Engineering
    root_id = 1311706520467144808 # foro solenium

    #root_id = 1357437462321958982 # SolAyura

    # dict_res = collect_all_chronological_summaries_by_channel(session=session, channel_id=root_id)
    # res = dict_res["channel_summary"]
    # print(res)

    asyncio.run(
        procces_all_peding_text_channel_summaries(session=session, semaphore=semophare, llm=llm, root_id=root_id)
    )
    

"""
python3 -m src.services.v1.DiscordGraph.DiscordContexChannnels.text_channels


"""

