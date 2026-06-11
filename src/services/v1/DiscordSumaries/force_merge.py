"""
Fuerza el merge de un chunk de discord_chronological_summary con el chunk
inmediatamente anterior del mismo canal.

Útil para chunks "vivos" (status=False) que llevan mucho tiempo sin crecer (canales
que se quedaron silenciosos) y que por sí solos nunca acumularán contenido
suficiente para madurar (no alcanzan T_MIN ni W_MAX_WEEKS).

Operación (dado el id de un chunk X):
  1. Localiza Y = chunk con start_time < X.start_time más reciente del mismo canal.
  2. Si Y no existe → no hay nada con que mergear, se aborta.
  3. Extiende Y para cubrir el rango de X:
       Y.end_time             = X.end_time
       Y.number_messages     += X.number_messages
       Y.summary              = None    (los mensajes detrás del resumen cambiaron)
       Y.alerts_done          = False   (el rango cambió → re-extraer alertas de Y)
       Y.state.{naive_rag,lightrag,graphiti}_status = None  (todo lo ingerido
                                          downstream quedó obsoleto → re-procesar)
       Y.lightrag_docs.pending_deletion = True  (si los hay, purgar y re-ingerir)
  4. Borra la fila de estado de X en discord_summary_state.
  5. Elimina el registro X.

La fila de discord_summary_state de X se elimina aquí (todo chunk tiene una desde su
creación, así que ya no puede actuar como bloqueante). En cambio, si X tiene
referencias en discord_chunk_embeddings o discord_lightrag_docs (FK sin ON DELETE
CASCADE), la rutina aborta sin tocar nada para no romper FKs — hay que limpiar primero
esas referencias.

Las alertas de X (discord_alerts.summary_id = X.id) NO bloquean el merge: la FK tiene
ON DELETE CASCADE, así que se borran junto con X. Es lo correcto, porque su contenido
pasa a Y y se recalculará al reprocesar Y (gracias a Y.alerts_done = False).

Uso:
    python3 -m src.services.v1.DiscordSumaries.force_merge <chunk_id>
"""

from sqlalchemy.orm import Session

from src import discord_models as models
from src.logging_config import get_logger

logger = get_logger(module_name="force_merge", DIR="DiscordSumaries")


def force_merge_with_previous(session: Session, chunk_id: int) -> bool:
    """Fusiona chunk_id en el chunk anterior de su canal. Devuelve True si se mergeó."""
    x = (
        session.query(models.DiscordChannelChronologicalSummary)
        .filter_by(id=chunk_id)
        .first()
    )
    if x is None:
        logger.warning("Chunk id=%s no encontrado", chunk_id)
        return False

    if x.status is True:
        logger.warning(
            "Chunk id=%s ya está marcado maduro (status=True); el merge igual procede",
            chunk_id,
        )

    y = (
        session.query(models.DiscordChannelChronologicalSummary)
        .filter(
            models.DiscordChannelChronologicalSummary.channel_id == x.channel_id,
            models.DiscordChannelChronologicalSummary.start_time < x.start_time,
        )
        .order_by(models.DiscordChannelChronologicalSummary.start_time.desc())
        .first()
    )
    if y is None:
        logger.warning(
            "Chunk id=%s no tiene predecesor en canal %s; nada que mergear",
            chunk_id, x.channel_id,
        )
        return False

    # Check defensivo: X no puede borrarse si lo referencian tablas con FK sin
    # ON DELETE CASCADE. La fila de discord_summary_state de X SÍ se elimina más
    # abajo (todo chunk tiene una desde su creación, así que ya no bloquea); los
    # embeddings y lightrag_docs siguen abortando: requieren limpieza propia.
    refs_emb = (
        session.query(models.DiscordChunkEmbeddings.id)
        .filter_by(summary_id=x.id).first()
    )
    refs_lr = (
        session.query(models.LightRagDocs.summary_id)
        .filter_by(summary_id=x.id).first()
    )
    if refs_emb or refs_lr:
        logger.error(
            "Chunk id=%s tiene referencias downstream — merge abortado. "
            "chunk_embeddings=%s, lightrag_docs=%s. "
            "Limpia esas referencias antes de reintentar.",
            chunk_id, bool(refs_emb), bool(refs_lr),
        )
        return False

    logger.info(
        "Merging X(id=%s, canal=%s, %s msgs, %s → %s) en Y(id=%s, %s msgs, %s → %s)",
        x.id, x.channel_id, x.number_messages, x.start_time, x.end_time,
        y.id, y.number_messages, y.start_time, y.end_time,
    )

    y.end_time = x.end_time
    y.number_messages = (y.number_messages or 0) + (x.number_messages or 0)
    y.summary = None
    y.alerts_done = False  # el contenido de Y cambió → re-extraer alertas
    session.add(y)

    # El contenido de Y cambió → todo lo ingerido downstream quedó obsoleto. Y es el
    # chunk anterior y puede estar maduro y YA ingerido en NaiveRag, LightRAG y/o
    # Graphiti, así que reseteamos los tres estados a NULL (= pendiente de re-procesar).
    y_state = (
        session.query(models.DiscordSummaryStatus)
        .filter_by(summary_id=y.id).first()
    )
    if y_state is not None:
        y_state.naive_rag_status = None
        y_state.lightrag_status = None
        y_state.graphiti_status = None
        session.add(y_state)
    else:
        # Defensivo: si Y no tuviera fila de estado, la creamos.
        session.add(models.DiscordSummaryStatus(summary_id=y.id))

    # Si Y ya tenía docs en LightRAG, su contenido cambió → marcar para borrado.
    # El pipeline de LightRAG consume pending_deletion=True para purgarlos y re-ingerir.
    session.query(models.LightRagDocs).filter_by(summary_id=y.id).update(
        {models.LightRagDocs.pending_deletion: True},
        synchronize_session=False,
    )

    # X desaparece: su fila de estado debe borrarse (FK sin ON DELETE CASCADE).
    x_state = (
        session.query(models.DiscordSummaryStatus)
        .filter_by(summary_id=x.id).first()
    )
    if x_state is not None:
        session.delete(x_state)

    session.delete(x)  # ON DELETE CASCADE borra las alertas de X (se recalcularán en Y)
    session.commit()

    logger.info(
        "OK. Y(id=%s) ahora cubre %s → %s con %s msgs y summary=None. X(id=%s) eliminado.",
        y.id, y.start_time, y.end_time, y.number_messages, x.id,
    )
    return True


if __name__ == "__main__":
    import argparse
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src import settings
    from src.logging_config import setup_base_logging

    setup_base_logging()


    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        force_merge_with_previous(session, 5162)
    finally:
        session.close()



"""
python3 -m src.services.v1.DiscordSumaries.force_merge


"""