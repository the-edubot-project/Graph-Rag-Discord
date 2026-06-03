import os
import re
import logging
from datetime import datetime
from typing import List, TypedDict, Dict

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from lightrag import LightRAG
from lightrag.llm.openai import openai_complete
from lightrag.llm.gemini import gemini_embed
from lightrag.utils import EmbeddingFunc

from src import settings
from src import discord_models as models
from src import lightrag_models as Lmodels

logger = logging.getLogger(__name__)

# LightRAG lee credenciales de os.environ, no de variables Python.
os.environ["POSTGRES_HOST"] = settings.DB_HOST
os.environ["POSTGRES_PORT"] = str(settings.DB_PORT)
os.environ["POSTGRES_USER"] = settings.DB_USER
os.environ["POSTGRES_PASSWORD"] = settings.DB_PASS
os.environ["POSTGRES_DATABASE"] = settings.DB_NAME_LIGHTRAG
os.environ["NEO4J_URI"] = settings.NEO4J_URI
os.environ["NEO4J_USERNAME"] = settings.NEO4J_USERNAME
os.environ["NEO4J_PASSWORD"] = settings.NEO4J_PASSWORD

# LLM: vLLM server (gemma-4-26b, OpenAI-compatible)
_VLLM_BASE_URL = "http://10.8.0.11:8003/v1"
_LLM_MODEL = "gemma-4-26b"

# Embeddings: Gemini (se mantiene para no re-indexar los vectores existentes)
_EMBED_DIM = 1536
_EMBED_MODEL = "gemini-embedding-001"

_rag: LightRAG | None = None


async def _get_rag() -> LightRAG:
    global _rag
    if _rag is None:
        gemini_embedding = EmbeddingFunc(
            embedding_dim=_EMBED_DIM,
            max_token_size=8000,
            model_name=_EMBED_MODEL,
            send_dimensions=True,
            func=gemini_embed.func,
        )
        _rag = LightRAG(
            working_dir=str(settings.ROOT / "data" / "rag_storage"),
            llm_model_func=openai_complete,
            llm_model_name=_LLM_MODEL,
            llm_model_kwargs={
                "base_url": _VLLM_BASE_URL,
                "api_key": "EMPTY",
            },
            embedding_func=gemini_embedding,
            kv_storage="PGKVStorage",
            doc_status_storage="PGDocStatusStorage",
            vector_storage="PGVectorStorage",
            graph_storage="Neo4JStorage",
        )
        await _rag.initialize_storages()
    return _rag


# Sesión separada hacia la DB de LightRAG (para sweep_pending_deletions y sync_processed_lightrag_docs).
engine = create_engine(settings.LIGHTRAG_CONN_STRING)
MySession2 = sessionmaker(bind=engine)
session2 = MySession2()


def safe_name(name: str) -> str:
    return re.sub(r"[^\w\-_. ]", "_", name)


async def delete_in_lightrag_status(session: Session, summary_ids: List[int]):
    """
    Borra cada documento de LightRAG y elimina el registro correspondiente de
    LightRagDocs en cuanto la librería confirma la eliminación.
    """
    summary_ids_set = set(summary_ids)
    records = session.query(models.LightRagDocs).filter(
        models.LightRagDocs.summary_id.in_(summary_ids_set)
    ).all()

    if not records:
        logger.info("delete_in_lightrag_status: no hay registros en LightRagDocs para los summary_ids dados")
        return

    rag = await _get_rag()

    for record in records:
        if record.lightrag_doc_id is None:
            logger.warning(
                "lightrag_doc_id es None para summary_id=%s, saltando",
                record.summary_id,
            )
            continue

        result = await rag.adelete_by_doc_id(record.lightrag_doc_id)

        if result.status in ("success", "not_found"):
            summary_record = session.query(models.DiscordChannelChronologicalSummary).filter_by(
                id=record.summary_id
            ).first()
            if summary_record:
                summary_record.status = None
                session.add(summary_record)
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


async def insert_to_light_rag(
    session: Session,
    summary_id: int,
    channel_id: int,
    start_time: datetime,
    end_time: datetime,
    summary: str,
):
    channel_record = session.query(models.DiscordChannel).filter_by(id=channel_id).first()

    if channel_record is None:
        raise ValueError(f"No se encontró DiscordChannel con id={channel_id}")

    channel_name = safe_name(channel_record.name)
    start_str = safe_name(start_time.strftime("%d/%m/%Y %H:%M"))
    end_str = safe_name(end_time.strftime("%d/%m/%Y %H:%M"))
    doc_name = f"{channel_record.id}_{channel_name}_from_{start_str}_to_{end_str}"

    # ID determinista: si se re-inserta el mismo summary no crea un duplicado en el grafo.
    doc_id = f"doc-summary-{summary_id}"

    existing = session.query(models.LightRagDocs).filter_by(summary_id=summary_id).first()
    if existing and existing.lightrag_doc_id is not None:
        logger.warning(
            "summary_id=%s ya está en LightRagDocs con doc_id=%s, saltando",
            summary_id, existing.lightrag_doc_id,
        )
        return

    logger.info("Insertando summary_id=%s canal=%s", summary_id, channel_record.name)

    rag = await _get_rag()
    track_id = await rag.ainsert(summary, ids=doc_id, file_paths=doc_name)

    logger.info("Insertado en LightRAG: doc_id=%s track_id=%s", doc_id, track_id)

    # ainsert bloquea hasta que el procesamiento termina: se puede marcar in_lightrag de inmediato.
    if existing:
        existing.lightrag_doc_id = doc_id
        existing.lightrag_track_id = track_id
        session.add(existing)
    else:
        session.add(models.LightRagDocs(
            summary_id=summary_id,
            lightrag_doc_id=doc_id,
            lightrag_track_id=track_id,
        ))

    summary_record = session.query(models.DiscordChannelChronologicalSummary).filter_by(
        id=summary_id
    ).first()
    if summary_record:
        summary_record.status = "in_lightrag"
        session.add(summary_record)

    session.commit()


# ── Funciones de compatibilidad para registros insertados con el flujo HTTP anterior ──────────


def sweep_pending_deletions(session: Session):
    """
    Verifica en la DB de LightRAG los registros con pending_deletion=True.
    Solo relevante para registros creados por el flujo HTTP anterior.
    """
    pending = session.query(models.LightRagDocs).filter_by(pending_deletion=True).all()

    if not pending:
        logger.info("sweep_pending_deletions: sin registros pendientes")
        return

    logger.info("sweep_pending_deletions: revisando %d registros", len(pending))

    deleted_count = 0
    still_pending_count = 0

    for record in pending:
        session2.expire_all()
        lightrag_record = session2.query(Lmodels.LightRagDocStatus).filter_by(
            id=record.lightrag_doc_id
        ).first()

        if lightrag_record is None:
            summary_record = session.query(models.DiscordChannelChronologicalSummary).filter_by(
                id=record.summary_id
            ).first()
            summary_record.status = None
            session.add(summary_record)
            session.delete(record)
            deleted_count += 1
            logger.info(
                "Eliminado de lightrag_docs: doc_id=%s summary_id=%s",
                record.lightrag_doc_id, record.summary_id,
            )
        else:
            still_pending_count += 1
            logger.info("Aún pendiente en LightRAG: doc_id=%s", record.lightrag_doc_id)

    session.commit()
    logger.info(
        "sweep completado: %d eliminados, %d aún pendientes",
        deleted_count, still_pending_count,
    )


class PendingTracks(TypedDict):
    lightrag_track_ids: List[str]
    lightrag_track_ids_dict: Dict[str, int]


def sync_processed_lightrag_docs(session: Session, pendingtracks: PendingTracks) -> int:
    """
    Busca en lightrag_doc_status los track_ids ya procesados y actualiza
    lightrag_doc_id en LightRagDocs.
    Solo relevante para registros insertados con el flujo HTTP anterior.
    """
    track_ids = pendingtracks.get("lightrag_track_ids")
    if not track_ids:
        return 0

    session2.expire_all()
    processed = (
        session2.query(Lmodels.LightRagDocStatus)
        .filter(
            Lmodels.LightRagDocStatus.track_id.in_(track_ids),
            Lmodels.LightRagDocStatus.status == "processed",
        )
        .all()
    )

    if not processed:
        logger.info("sync_processed_lightrag_docs: ningún track_id procesado aún.")
        return 0

    track_to_doc_id = {r.track_id: r.id for r in processed}
    lightrag_track_ids_dict = pendingtracks.get("lightrag_track_ids_dict")

    updated = 0
    for track_id, doc_id in track_to_doc_id.items():
        count = (
            session.query(models.LightRagDocs)
            .filter(
                models.LightRagDocs.lightrag_track_id == track_id,
                models.LightRagDocs.lightrag_doc_id.is_(None),
            )
            .update({"lightrag_doc_id": doc_id})
        )
        updated += count

        summary_id = lightrag_track_ids_dict[track_id]
        record = session.query(models.DiscordChannelChronologicalSummary).filter_by(
            id=summary_id
        ).first()
        record.status = "in_lightrag"
        session.add(record)

    session.commit()
    logger.info("sync_processed_lightrag_docs: %d docs actualizados.", updated)
    return updated


def get_pending_track_ids(session: Session) -> PendingTracks:
    records = session.query(models.LightRagDocs).filter(
        models.LightRagDocs.lightrag_doc_id.is_(None)
    ).all()

    lightrag_track_ids = []
    lightrag_track_ids_dict: Dict[str, int] = {}
    for r in records:
        if r.lightrag_track_id is None:
            raise ValueError(f"lightrag_track_id es None para summary_id={r.summary_id}")
        lightrag_track_ids.append(r.lightrag_track_id)
        lightrag_track_ids_dict[r.lightrag_track_id] = r.summary_id

    return {
        "lightrag_track_ids": lightrag_track_ids,
        "lightrag_track_ids_dict": lightrag_track_ids_dict,
    }


if __name__ == "__main__":
    import asyncio
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src import settings

    engine = create_engine(settings.DB_DISCORD_CONN_STRING)
    MySession = sessionmaker(bind=engine)
    session = MySession()

    sweep_pending_deletions(session=session)


"""
python3 -m src.services.v1.DiscordGraph.lightrag_crud



"""
