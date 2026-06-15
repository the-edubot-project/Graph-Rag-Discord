"""
Pipeline completo de extracción/resumen/embeddings de Discord, en orden:

  1. rechunk_all_available_channels  — chunkeniza los canales con mensajes nuevos.
  2. seed_mature_status              — marca como maduros (inmutables) los chunks
                                       que cumplen la política de tokens/tiempo.
  3. make_all_pending_summaries      — genera/regenera los resúmenes pendientes.
  4. make_text_embeddings_batch      — embeddings NaiveRag de los chunks resumidos.

Pensado para ejecutarse de forma programada (ver src/scheduler.py y docker-compose),
o a mano:

    python3 -m src.pipeline
"""

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src import settings
from src.logging_config import get_logger, setup_base_logging
from src.services.v1.DiscordSumaries.chunking import rechunk_all_available_channels
from src.services.v1.DiscordSumaries.mark_mature import seed_mature_status
from src.services.v1.DiscordSumaries.summary_chunks import make_all_pending_summaries
from src.services.v1.NaiveRag.make_text_embeddings_google import make_text_embeddings_batch

logger = get_logger(module_name="pipeline", DIR="pipeline")

# Parámetros del pipeline (mismos defaults que los __main__ de cada módulo).
SUMMARY_MODEL = "deepseek-v4-flash"
SUMMARY_TEMPERATURE = 0.2
SUMMARY_CONCURRENCY = 4
EMBEDDING_MODEL = "gemini-embedding-001"


async def run_pipeline() -> None:
    """Ejecuta los cuatro pasos en orden sobre una única sesión."""
    from langchain_deepseek import ChatDeepSeek
    from google import genai

    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        logger.info("=== Pipeline 1/4: rechunk_all_available_channels ===")
        rechunk_all_available_channels(session=session)

        logger.info("=== Pipeline 2/4: seed_mature_status ===")
        seed_mature_status(session=session)

        logger.info("=== Pipeline 3/4: make_all_pending_summaries ===")
        llm = ChatDeepSeek(
            model=SUMMARY_MODEL,
            temperature=SUMMARY_TEMPERATURE,
            api_key=settings.DEEPSEEK_API_KEY,
        )
        semaphore = asyncio.Semaphore(SUMMARY_CONCURRENCY)
        await make_all_pending_summaries(
            session=session, semaphore=semaphore, llm=llm, llm_model=SUMMARY_MODEL
        )

        logger.info("=== Pipeline 4/4: make_text_embeddings_batch ===")
        # Sin tokenizer local: la API de Google devuelve token_count, así evitamos
        # descargar el modelo de Gemma dentro del contenedor.
        client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        make_text_embeddings_batch(
            session=session, client=client, embedding_model=EMBEDDING_MODEL
        )

        logger.info("=== Pipeline COMPLETO ===")
    finally:
        session.close()


def main() -> None:
    setup_base_logging()
    asyncio.run(run_pipeline())


if __name__ == "__main__":
    main()
