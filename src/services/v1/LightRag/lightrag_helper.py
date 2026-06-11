
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, TypedDict, Dict
from lightrag import LightRAG
from datetime import datetime

from src.logging_config import get_logger
from src import discord_models as dmodels
from src import lightrag_models as lmodels
from src import settings
import os
import re


logger = get_logger(module_name="lightrag_helper", DIR="LightRag")





def mark_ready_for_lightrag(session : Session):
    """
    rutina para marcar los chunks inmutables con status
    
    """

    records = session.query(
        dmodels.DiscordChannelChronologicalSummary.id
    ).join(
        dmodels.DiscordSummaryStatus,
        dmodels.DiscordSummaryStatus.summary_id == dmodels.DiscordChannelChronologicalSummary.id
    ).filter(
        dmodels.DiscordChannelChronologicalSummary.status == True
    ).all()
    
    if not records:
        logger.info("No hay chunks que hayna pasado al estado inmutable (maduro)")
        return
    
    ids = [r.id for r in records]    

    status_records = session.query(dmodels.DiscordSummaryStatus).filter(
        dmodels.DiscordSummaryStatus.summary_id.in_(ids)
    ).all()

    if not status_records:
        logger.warning("status_records esta vacio")
        return
    
    for r in status_records:
        r.lightrag_status = "ready"
        session.add(r)
    
    session.commit()
    






async def delete_in_lightrag_status(session: Session, lightrag : LightRAG, summary_ids: List[int]):
    """
    Borra cada documento de LightRAG y elimina el registro correspondiente de
    LightRagDocs en cuanto la librería confirma la eliminación.
    """
    summary_ids_set = set(summary_ids)
    records = session.query(dmodels.LightRagDocs).filter(
        dmodels.LightRagDocs.summary_id.in_(summary_ids_set)
    ).all()

    if not records:
        logger.info("delete_in_lightrag_status: no hay registros en LightRagDocs para los summary_ids dados")
        return


    for record in records:
        if record.lightrag_doc_id is None:
            logger.warning(
                "lightrag_doc_id es None para summary_id=%s, saltando",
                record.summary_id,
            )
            continue

        result = await lightrag.adelete_by_doc_id(record.lightrag_doc_id)

        if result.status in ("success", "not_found"):
            status_records = session.query(dmodels.DiscordSummaryStatus).filter_by(
                summary_id=record.summary_id
            ).first()
            if status_records:
                status_records.lightrag_status = None
                session.add(status_records)
            session.delete(record)
            logger.info(
                "Eliminado doc_id=%s summary_id=%s (status=%s)",
                record.lightrag_doc_id, record.summary_id, result.status,
            )
        else:
            logger.warning(
                "Fallo al eliminar doc_id=%s summary_id=%s: %s",
                record.lightrag_doc_id, record.summary_id, result.message,
            )
    
    session.commit()
            



def safe_name(name: str) -> str:
    return re.sub(r"[^\w\-_. ]", "_", name)



async def insert_to_light_rag(
    session: Session,
    lightrag : LightRAG,
    summary_id: int,
    channel_id: int,
    start_time: datetime,
    end_time: datetime,
    summary: str,
):
    """
    Funcion para incertar documentos en lightrag
    
    """
    channel_record = session.query(dmodels.DiscordChannel).filter_by(id=channel_id).first()

    if channel_record is None:
        raise ValueError(f"No se encontró DiscordChannel con id={channel_id}")

    channel_name = safe_name(channel_record.name)
    start_str = safe_name(start_time.strftime("%d/%m/%Y %H:%M"))
    end_str = safe_name(end_time.strftime("%d/%m/%Y %H:%M"))
    doc_name = f"{channel_record.id}_{channel_name}_from_{start_str}_to_{end_str}"

    # ID determinista: si se re-inserta el mismo summary no crea un duplicado en el grafo.
    doc_id = f"doc-summary-{summary_id}"

    existing = session.query(dmodels.LightRagDocs).filter_by(summary_id=summary_id).first()
    if existing and existing.lightrag_doc_id is not None:
        logger.warning(
            "summary_id=%s ya está en LightRagDocs con doc_id=%s, saltando",
            summary_id, existing.lightrag_doc_id,
        )
        return

    logger.info("Insertando summary_id=%s canal=%s", summary_id, channel_record.name)

    track_id = await lightrag.ainsert(summary, ids=doc_id, file_paths=doc_name)

    logger.info("Insertado en LightRAG: doc_id=%s track_id=%s", doc_id, track_id)

    # ainsert bloquea hasta que el procesamiento termina: se puede marcar in_lightrag de inmediato.
    if existing:
        existing.lightrag_doc_id = doc_id
        existing.lightrag_track_id = track_id
        session.add(existing)
    else:
        session.add(dmodels.LightRagDocs(
            summary_id=summary_id,
            lightrag_doc_id=doc_id,
            lightrag_track_id=track_id,
        ))

        status_record = session.query(dmodels.DiscordSummaryStatus).filter_by(
            id=summary_id
        ).first()

        status_record.lightrag_status = "in_lightrag"

        
        

