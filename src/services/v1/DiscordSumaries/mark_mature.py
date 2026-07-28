"""
Siembra en discord_summary_state los chunks de discord_chronological_summary que ya
están "maduros" (no se volverán a re-chunkenizar ni re-resumir).

Cada ejecución:
  1. Lee qué summary_id ya están en discord_summary_state → se ignoran.
  2. Para cada chunk aún no marcado, decide si está maduro
     (chunking.is_chunk_mature, misma regla que el chunker).
  3. Si está maduro, inserta un registro en discord_summary_state con summary_id y
     los demás campos en NULL (los completan los pipelines downstream).

No genera resúmenes ni modifica los chunks; solo siembra el estado. Es idempotente:
correrlo de nuevo solo añade los chunks que hayan madurado desde la última vez.

Uso:
    python3 -m src.services.v1.DiscordSumaries.mark_mature
"""

from sqlalchemy.orm import Session

from src import discord_models as models
from src.logging_config import get_logger
from src.services.v1.DiscordSumaries.chunking import is_chunk_mature

logger = get_logger(module_name="mark_mature", DIR="DiscordSumaries", to_db=True)


# def seed_mature_states(session: Session) -> int:
#     """Inserta en discord_summary_state los chunks maduros aún no marcados. Devuelve el nº insertado."""
#     already_marked = {
#         row[0] for row in session.query(models.DiscordSummaryStatus.summary_id).all()
#     }
#     logger.info("discord_summary_state ya contiene %s registro(s)", len(already_marked))

#     records = (
#         session.query(models.DiscordChannelChronologicalSummary)
#         .order_by(
#             models.DiscordChannelChronologicalSummary.channel_id,
#             models.DiscordChannelChronologicalSummary.start_time,
#         )
#         .all()
#     )
#     logger.info("Revisando %s chunk(s) de discord_chronological_summary", len(records))

#     inserted = 0
#     skipped_existing = 0
#     not_mature = 0

#     for rec in records:
#         if rec.id in already_marked:
#             skipped_existing += 1
#             continue

#         if is_chunk_mature(session, rec):
#             session.add(models.DiscordSummaryStatus(summary_id=rec.id))
#             inserted += 1
#             logger.debug(
#                 "[canal %s] chunk id=%s maduro → insertado en discord_summary_state",
#                 rec.channel_id, rec.id,
#             )
#         else:
#             not_mature += 1
#             logger.debug("[canal %s] chunk id=%s aún vivo → no se marca", rec.channel_id, rec.id)

#     session.commit()
#     logger.info(
#         "Hecho. Nuevos maduros insertados: %s | ya marcados (ignorados): %s | aún vivos: %s",
#         inserted, skipped_existing, not_mature,
#     )
#     return inserted




def seed_mature_status(session: Session):
    
    records = session.query(models.DiscordChannelChronologicalSummary).filter(
        models.DiscordChannelChronologicalSummary.status == False
    ).all()
    logger.info(f"Hey {len(records)} registros en discord_chronological_summary que no estan maduros")

    count = 0
    for r in records:
        mature = is_chunk_mature(session, r)
        if mature:
            count += 1
            r.status = True
            session.add(r)
    session.commit()
    logger.info(f"Hay {count} nuevos registro maduros")




if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src import settings
    from src.logging_config import setup_base_logging

    setup_base_logging()

    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    try:
        seed_mature_status(session)
    finally:
        session.close()


"""
python3 -m src.services.v1.DiscordSumaries.mark_mature


"""