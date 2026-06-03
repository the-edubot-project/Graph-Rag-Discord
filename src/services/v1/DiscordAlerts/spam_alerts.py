

from sqlalchemy.orm import Session
from src import discord_models as models
from datetime import datetime
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import JsonOutputParser
from .prompts import ALERT_DETECTION_PROMPT_2
from .format_db_messages import format_db_messageses

from typing import List, TypedDict, Dict, Any, Optional
import asyncio

from src.logging_config import get_logger
logger = get_logger(module_name="spam_alerts", DIR="DiscordSumaries")


parser = JsonOutputParser()




class AlertChunkResult(TypedDict):
    content: Optional[str]
    error: Optional[str]
    usage_metadata: Optional[Dict[str, Any]]
    chunk_id: int
    channel_id: int
    start_date: datetime
    end_date: datetime
    llm_model: str


async def process_single_chunk(
    llm: BaseChatModel,
    llm_model: str,
    prompt: str,
    chunk_id: int,
    channel_id: int,
    start_date: datetime,
    end_date: datetime,
    semaphore: asyncio.Semaphore,
) -> AlertChunkResult:
    # Siempre devolvemos el dict (con chunk_id/channel_id) aunque la llamada falle,
    # para poder atribuir e informar los fallos al final del proceso.
    base = {
        "chunk_id": chunk_id,
        "channel_id": channel_id,
        "start_date": start_date,
        "end_date": end_date,
        "llm_model": llm_model,
    }
    async with semaphore:
        try:
            ai_message = await llm.ainvoke(prompt)
            return {
                **base,
                "content": ai_message.content,
                "error": None,
                "usage_metadata": ai_message.usage_metadata,
            }
        except Exception as e:
            logger.error(f"fallo en la llamada LLM para chunk {chunk_id} (canal {channel_id}): \n {e} \n\n")
            return {**base, "content": None, "error": str(e), "usage_metadata": None}




def get_all_alert_data_task(session: Session) -> List[Dict[str, Any]]:
    """
    Construye una lista plana de prompts pendientes para extraer alertas, reusando
    las fronteras de chunk del pipeline de summaries (DiscordChannelChronologicalSummary)
    en vez de un único rango gigante por canal.

    Un chunk está pendiente cuando alerts_done == False. Ese flag funciona igual que
    `summary` en el pipeline de chunking:
      - chunk nuevo                      → alerts_done False (default) → se procesa.
      - chunk vivo cuyo contenido cambió → chunking.py lo reabre y pone alerts_done
                                           False (junto a summary=None) → se reprocesa.
      - chunk procesado y sin cambios    → alerts_done True → se salta sin recosto,
                                           aunque no haya tenido ninguna alerta.

    make_all_pending_alerts marca alerts_done = True al terminar cada chunk, y reemplaza
    (delete+insert por clave channel_id+start_time) las alertas previas del rango.
    """
    logger.info("get_all_alert_data_task")

    chunk_records = (
        session.query(models.DiscordChannelChronologicalSummary)
        .filter(models.DiscordChannelChronologicalSummary.alerts_done.is_(False))
        .order_by(
            models.DiscordChannelChronologicalSummary.channel_id,
            models.DiscordChannelChronologicalSummary.start_time,
        )
        .all()
    )

    logger.info(f"Hay {len(chunk_records)} chunks pendientes de alertas")

    # Cache channel_id -> name para no repetir consultas.
    channel_names: Dict[int, str] = {}

    result: List[Dict[str, Any]] = []

    for chunk in chunk_records:
        format_messages = format_db_messageses(
            session,
            channel_id=chunk.channel_id,
            summary_from=chunk.start_time,
            summary_end=chunk.end_time,
        )

        if not format_messages:
            continue

        if chunk.channel_id not in channel_names:
            channel = session.query(models.DiscordChannel).filter_by(id=chunk.channel_id).first()
            channel_names[chunk.channel_id] = channel.name if channel else str(chunk.channel_id)

        prompt = ALERT_DETECTION_PROMPT_2.format(
            messages=format_messages,
            channel_name=channel_names[chunk.channel_id],
            start_date=chunk.start_time,
            end_date=chunk.end_time,
        )

        result.append({
            "prompt": prompt,
            "chunk_id": chunk.id,
            "channel_id": chunk.channel_id,
            "start_date": chunk.start_time,
            "end_date": chunk.end_time,
        })

    logger.info(f"Hay {len(result)} chunks con mensajes por analizar")
    return result




async def make_all_pending_alerts(
    session: Session,
    semaphore: asyncio.Semaphore,
    llm: BaseChatModel,
    llm_model: str,
):
    logger.info("make_all_pending_alerts")

    pending = get_all_alert_data_task(session=session)

    if not pending:
        logger.warning("No hay alertas pendientes por procesar")
        return None

    logger.info("Prompts conseguidos")

    tasks = [
        process_single_chunk(
            llm=llm,
            llm_model=llm_model,
            prompt=p["prompt"],
            chunk_id=p["chunk_id"],
            channel_id=p["channel_id"],
            start_date=p["start_date"],
            end_date=p["end_date"],
            semaphore=semaphore,
        ) for p in pending
    ]
    logger.info("tasks conseguidos")

    total_tasks = len(tasks)
    count = 0
    alerts_saved = 0
    input_tokens, output_tokens = 0, 0
    # Chunks que NO quedaron procesados (siguen alerts_done=False y se reintentarán).
    llm_failures: List[Dict[str, Any]] = []    # falló la llamada al modelo
    parse_failures: List[Dict[str, Any]] = []  # respondió pero el JSON no se pudo parsear

    for task in asyncio.as_completed(tasks):
        result = await task

        if not result:
            continue

        result: AlertChunkResult

        # Fallo en la llamada al modelo: no hubo respuesta que parsear.
        if not result.get("content"):
            llm_failures.append({
                "chunk_id": result["chunk_id"],
                "channel_id": result["channel_id"],
                "error": result.get("error"),
            })
            continue

        try:
            parsed = parser.parse(result["content"])
        except Exception as e:
            snippet = (result["content"] or "")[:500]
            logger.error(
                f"JSON inválido en chunk {result['chunk_id']} (canal {result['channel_id']}): {e}\n"
                f"--- contenido recibido (primeros 500 chars): ---\n{snippet}\n\n"
            )
            parse_failures.append({
                "chunk_id": result["chunk_id"],
                "channel_id": result["channel_id"],
                "error": str(e),
            })
            continue

        alerts = parsed.get("alerta", []) if isinstance(parsed, dict) else []

        meta = result.get("usage_metadata") or {}
        chunk_in = meta.get("input_tokens", 0)
        chunk_out = meta.get("output_tokens", 0)
        input_tokens += chunk_in
        output_tokens += chunk_out

        # Reemplazo idempotente: borramos las alertas previas de este chunk (por su FK
        # summary_id) antes de reinsertar. Necesario para el chunk vivo, que se
        # reprocesa en cada corrida; un chunk maduro ya procesado ni siquiera llega
        # aquí (se filtró en get_all_alert_data_task).
        # NOTA: esto descarta el alert_status downstream de las alertas borradas del
        # chunk vivo (se reenviarían). Es inherente al modelo de chunk "vivo".
        session.query(models.DiscordAlert).filter_by(
            summary_id=result["chunk_id"]
        ).delete()

        # Atribuimos el costo de la llamada solo al primer alert del chunk para que
        # SUM(input_tokens)/SUM(output_tokens) refleje el costo real sin duplicar.
        for i, alert in enumerate(alerts):
            try:
                db_record = models.DiscordAlert(
                    summary_id=result["chunk_id"],
                    channel_id=result["channel_id"],
                    start_time=result["start_date"],
                    end_time=result["end_date"],
                    severity=alert["severity"],
                    type=alert.get("type"),
                    description=alert["description"],
                    input_tokens=chunk_in if i == 0 else 0,
                    output_tokens=chunk_out if i == 0 else 0,
                    model=result["llm_model"],
                )
                session.add(db_record)
                alerts_saved += 1
            except (KeyError, TypeError) as e:
                logger.error(f"alerta mal formada en canal {result['channel_id']}: {alert} \n {e} \n\n")

        # Marcar el chunk como procesado para alertas (aunque hayan sido 0).
        session.query(models.DiscordChannelChronologicalSummary).filter_by(
            id=result["chunk_id"]
        ).update({"alerts_done": True})

        session.commit()
        count += 1
        logger.info(f"--- [Progreso: {count}/{total_tasks}] Canal {result['channel_id']}: {len(alerts)} alertas.")

    logger.info(f"\n--- ✨ ¡PROCESO FINALIZADO!")
    logger.info(f"--- 📊 Chunks procesados OK: {count}/{total_tasks}")
    logger.info(f"--- 📊 Alertas guardadas: {alerts_saved}")
    logger.info(f"--- 📊 Tokens totales: In: {input_tokens} | Out: {output_tokens}")

    if llm_failures:
        logger.warning(
            f"--- ⚠️ {len(llm_failures)} chunk(s) con fallo en la llamada LLM: "
            f"{[f['chunk_id'] for f in llm_failures]}"
        )
    if parse_failures:
        logger.warning(
            f"--- ⚠️ {len(parse_failures)} chunk(s) con JSON inválido: "
            f"{[f['chunk_id'] for f in parse_failures]}"
        )
    if llm_failures or parse_failures:
        logger.warning(
            "--- ↻ Estos chunks siguen alerts_done=False y se reintentarán en la próxima corrida."
        )

    return {
        "processed": count,
        "total": total_tasks,
        "alerts_saved": alerts_saved,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "llm_failures": llm_failures,
        "parse_failures": parse_failures,
    }




if __name__ == "__main__":
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from langchain_deepseek import ChatDeepSeek

    from src import settings  # su import dispara load_dotenv() → DEEPSEEK_API_KEY al entorno
    from src.logging_config import setup_base_logging

    # Modelo y concurrencia (ajústalos según el rate limit de tu cuenta DeepSeek).
    LLM_MODEL = "deepseek-v4-flash"
    MAX_CONCURRENCY = 5

    setup_base_logging()

    engine = create_engine(settings.DB_DISCORD_CONN_STRING)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    llm = ChatDeepSeek(
        model=LLM_MODEL,
        temperature=0,  # extracción determinista
        api_key=os.getenv("DEEPSEEK_API_KEY"),
    )

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    try:
        asyncio.run(
            make_all_pending_alerts(
                session=session,
                semaphore=semaphore,
                llm=llm,
                llm_model=LLM_MODEL,
            )
        )
    finally:
        session.close()


"""
python3 -m src.services.v1.DiscordAlerts.spam_alerts
"""




