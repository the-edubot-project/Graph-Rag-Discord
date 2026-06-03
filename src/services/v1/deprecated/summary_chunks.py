import asyncio
from sqlalchemy.orm import Session
from src import discord_models as models
from datetime import datetime

from langchain_core.language_models.chat_models import BaseChatModel
from .prompts import SUMMARY_DISCORD_MESSAGES_1

import re
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, TypedDict, Dict, Any, Optional

from src.logging_config import get_logger
logger = get_logger(module_name="summaery", DIR="ChronologicalSummary_v1")


def get_messages(session: Session, channel_id: int, summary_from: datetime, summary_end: datetime):
    # 1. Recuperar todos los mensajes del rango de una sola vez
    message_content_records = session.query(models.DiscordMessage).filter(
        models.DiscordMessage.channel_id == channel_id,
        models.DiscordMessage.message_create_at >= summary_from,
        models.DiscordMessage.message_create_at <= summary_end
    ).order_by(models.DiscordMessage.message_create_at.asc()).all()

    if not message_content_records:
        return ""

    # 2. Crear un mapa de UserID -> Name y MessageID -> MessageRecord
    # Esto evita consultas repetitivas a la base de datos (N+1)
    user_map = {str(msg.user_id): msg.user_name for msg in message_content_records}
    msg_map = {msg.id: msg for msg in message_content_records}

    # 3. Función para reemplazar menciones <@ID> por @Nombre
    def replace_mentions(text, mapping):
        if not text: return ""
        # Busca el patrón <@números>
        return re.sub(r'<@!?(\d+)>', lambda m: f"@{mapping.get(m.group(1), 'usuario_desconocido')}", text)

    # Plantillas optimizadas
    TEMPLATE_1 = "User: {user_name}  | Date: {date}\nContent: {content}\n\n" # (ID: {user_id})
    TEMPLATE_2 = "User: {user_name}  | Date: {date} | Reply to: {reply_to_name}\nContent: {content}\n\n" # (ID: {user_id})

    final_transcript = []

    for obj in message_content_records:
        try:
            # Limpiar el contenido reemplazando IDs por nombres
            clean_content = replace_mentions(obj.content, user_map)
            date_str = obj.message_create_at.strftime("%d/%m/%Y %H:%M")
            
            # Lógica de respuesta
            if obj.reply_to:
                # Intentamos buscar el nombre en nuestro mapa local primero
                parent_msg = msg_map.get(obj.reply_to)
                if parent_msg:
                    reply_name = parent_msg.user_name
                else:
                    # Si la respuesta es a un mensaje fuera de este rango de tiempo,
                    # podrías hacer una consulta rápida o poner "mensaje previo"
                    reply_name = "usuario_en_hilo_anterior"
                
                msg_text = TEMPLATE_2.format(
                    user_name=obj.user_name,
                    #user_id=obj.user_id,
                    date=date_str,
                    reply_to_name=reply_name,
                    content=clean_content
                )
            else:
                msg_text = TEMPLATE_1.format(
                    user_name=obj.user_name,
                    #user_id=obj.user_id,
                    date=date_str,
                    content=clean_content
                )
            
            final_transcript.append(msg_text)

        except Exception as e:
            print(f"Error procesando mensaje {obj.id}: {e}")
        
    return "".join(final_transcript)



class ProccesSingleChunk(TypedDict):
    summary : str
    usage_metadata : Dict[str, Any]
    idx : int




async def process_single_chunk(llm : BaseChatModel, prompt : str, idx : int, semaphore : asyncio.Semaphore) -> ProccesSingleChunk:
    print("\n")
    print("****** precess_single_chunk")
    async with semaphore:
        try:
            ai_message = await llm.ainvoke(prompt)
            print(f"usage_metadata: {ai_message.usage_metadata}, \n\n numero de caracteres: {len(ai_message.content)} \n\n\n")
            return {"summary": ai_message.content, "usage_metadata":ai_message.usage_metadata, "idx":idx}
        except Exception as e:
            logger.info(f"error procesando en el registro {idx} de DiscordChannelChronologicalSummary: \n {e} \n\n")
            return None





def collect_all_pending_summaries(session: Session) -> List[str]:
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
        print("summary_records es vacio")
        return None
    
    print(f"Hay {len(summary_records)} registros en DiscordChannelChronologicalSummary que su status es None")

    for obj in summary_records:
        messages = get_messages(session, channel_id=obj.channel_id, summary_from=obj.start_time, summary_end=obj.end_time)
        if messages:
            prompt = SUMMARY_DISCORD_MESSAGES_1.format(messages=messages)
            all_tasks.append({"prompt": prompt, "idx": obj.id})
        
    return all_tasks







async def make_all_pending_summaries(session : Session, semaphore : asyncio.Semaphore, llm : BaseChatModel):
    prompts = collect_all_pending_summaries(session=session)

    if prompts is None:
        print("prompts es vacio")
        return None
    
    print("Prompts conseguidos")
    
    tasks = [
        process_single_chunk(
            llm=llm,
            prompt=p["prompt"],
            idx=p["idx"],
            semaphore=semaphore,
        ) for p in prompts
    ]
    print("tasks conseguidos")

    # result : List[ProccesSingleChunk] = await asyncio.gather(*tasks)
    # total_tasks = len(result)
    total_tasks = len(tasks)

    count = 0
    input_tokens, output_tokens = 0, 0

    for task in asyncio.as_completed(tasks):
        result = await task

        if result and result["summary"]:
            db_record = session.query(models.DiscordChannelChronologicalSummary).filter_by(id=result["idx"]).first()

            if db_record:
                db_record.summary = result["summary"]
                db_record.status = "ready"
                
                print(f"guardando summary con id {db_record.id} ")

                meta = result.get("usage_metadata")
                if meta:
                    input_tokens += meta.get("input_tokens", 0)
                    output_tokens += meta.get("output_tokens", 0)
                
                session.add(db_record)
                session.commit() 

                count += 1
                print(f"--- [Progreso: {count}/{total_tasks}] Registro {result['idx']} guardado correctamente.")


    print(f"\n--- ✨ ¡PROCESO FINALIZADO!")
    print(f"--- 📊 Resúmenes guardados: {count}")
    print(f"--- 📊 Tokens totales: In: {input_tokens} | Out: {output_tokens}")







