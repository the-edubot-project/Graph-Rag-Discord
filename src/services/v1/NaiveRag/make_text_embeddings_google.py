"""
Generación de embeddings de chunks de Discord para NaiveRag, en BATCH y usando
directamente el cliente de google-genai (sin la abstracción de langchain).

Análogo a make_text_embeddings.py, pero:
  - Embebe en LOTES: embed_content acepta una lista en `contents`, así que agrupamos
    muchos textos por llamada en vez de uno a uno.
  - Usa google.genai.Client directamente (sin GoogleGenerativeAIEmbeddings).
  - Cuenta tokens de forma rigurosa con el conteo que devuelve la PROPIA API
    (ContentEmbedding.statistics.token_count). Si la API no lo trae poblado, cae a un
    tokenizer local (huggingface `tokenizers`, p.ej. Gemma) y, en último caso, chars/4.
  - Diferencia la tarea con task_type="RETRIEVAL_DOCUMENT" (lo propio de
    gemini-embedding-001); NO usa prefijos manuales tipo "title: ... | text: ..." (eso
    es de EmbeddingGemma y aquí solo ensuciaría el vector).

Selección de chunks (igual que make_text_embeddings.py): naive_rag_status IS NULL
(lo ponen chunking.py / force_merge.py cuando el contenido cambia, o arranca NULL al
crearse el chunk) y summary != NULL (summary_chunks.py ya corrió). Al completar TODOS
los (sub)embeddings de un chunk, se marca su naive_rag_status='ready'.

El batching es CROSS-CHUNK: aplanamos todos los (sub)textos de todos los chunks
pendientes en una sola lista y la troceamos en lotes de `batch_size`. Así se aprovecha
el batch aunque cada chunk produzca un único texto (sin text_spliter).

Uso:
    python3 -m src.services.v1.NaiveRag.make_text_embeddings_batch
"""

from typing import Iterable, Iterator, Sequence

from sqlalchemy.orm import Session
from langchain_text_splitters.base import TextSplitter
from google import genai
from google.genai import types
from tokenizers import Tokenizer

from src import discord_models as models
from src.logging_config import get_logger
from . import conf

logger = get_logger(module_name="make_text_embeddings_batch", DIR="NaiveRag")


# ──────────────────────────── helpers ────────────────────────────

def _batched(seq: Sequence, n: int) -> Iterator[Sequence]:
    """Trocea `seq` en lotes de tamaño máximo `n`."""
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _token_count(embedding: types.ContentEmbedding, sent_text: str,
                 tokenizer: Tokenizer | None) -> int:
    """
    Tokens del texto realmente enviado a embeber, en orden de rigor:
      1. statistics.token_count que devuelve la API (conteo exacto de Google);
      2. tokenizer local (p.ej. Gemma) si se pasó;
      3. heurística chars/4.
    """
    stats = getattr(embedding, "statistics", None)
    if stats is not None and getattr(stats, "token_count", None) is not None:
        return int(stats.token_count)
    if tokenizer is not None:
        return len(tokenizer.encode(sent_text).ids)
    return len(sent_text) // 4


# ──────────────────────────── rutina principal ────────────────────────────

def make_text_embeddings_batch(
    session: Session,
    client: genai.Client,
    embedding_model: str,
    text_spliter: TextSplitter | None = None,
    *,
    task_type: str | None = "RETRIEVAL_DOCUMENT",
    output_dimensionality: int | None = conf.GOOGLE_EMBEDDING_OUTPUT_DIM,
    batch_size: int = conf.GOOGLE_EMBEDDING_BATCH_SIZE,
    tokenizer: Tokenizer | None = None,
) -> None:
    # Chunks pendientes de (re)embeber. Una fila por chunk (summary_id es PK de
    # DiscordSummaryStatus y el join al resumen es 1-a-1).
    records = (
        session.query(
            models.DiscordSummaryStatus.summary_id,
            models.DiscordChannelChronologicalSummary.summary,
        )
        .join(
            models.DiscordChannelChronologicalSummary,
            models.DiscordChannelChronologicalSummary.id == models.DiscordSummaryStatus.summary_id,
        )
        .filter(
            models.DiscordSummaryStatus.naive_rag_status.is_(None),
            models.DiscordChannelChronologicalSummary.summary.is_not(None),
        )
        .all()
    )
    if not records:
        logger.info("No hay chunks pendientes de embeber (naive_rag_status IS NULL).")
        return

    # Borramos los embeddings previos de esos chunks (obsoletos si el chunk mutó; nada
    # que borrar si es nuevo). Un único DELETE masivo.
    summary_ids = {r.summary_id for r in records}
    session.query(models.DiscordChunkEmbeddings).filter(
        models.DiscordChunkEmbeddings.summary_id.in_(summary_ids)
    ).delete(synchronize_session=False)
    session.commit()

    # Aplanamos a items (summary_id, text), expandiendo sub-chunks si hay splitter.
    # `remaining` lleva la cuenta de cuántos items faltan por chunk, para marcar
    # 'ready' solo cuando se completan TODOS los sub-embeddings de ese chunk.
    items: list[dict] = []
    remaining: dict[int, int] = {}
    for r in records:
        parts = text_spliter.split_text(r.summary) if text_spliter else [r.summary]
        parts = [p for p in parts if p and p.strip()]
        remaining[r.summary_id] = len(parts)
        for p in parts:
            items.append({"summary_id": r.summary_id, "text": p})

    # Chunks cuyo resumen quedó vacío tras el split: nada que embeber → 'ready' directo.
    empty_ids = [sid for sid, n in remaining.items() if n == 0]
    if empty_ids:
        logger.warning("%s chunk(s) sin texto embebible; se marcan 'ready' sin embeddings.", len(empty_ids))
        session.query(models.DiscordSummaryStatus).filter(
            models.DiscordSummaryStatus.summary_id.in_(empty_ids)
        ).update({models.DiscordSummaryStatus.naive_rag_status: "ready"}, synchronize_session=False)
        session.commit()

    if not items:
        return

    config = types.EmbedContentConfig(
        task_type=task_type,
        output_dimensionality=output_dimensionality,
    )

    logger.info(
        "Embeibiendo %s texto(s) de %s chunk(s) en lotes de %s (modelo=%s, dim=%s).",
        len(items), len(records), batch_size, embedding_model, output_dimensionality,
    )

    total_done = 0
    for batch in _batched(items, batch_size):
        # gemini-embedding-001 usa task_type (en `config`) para diferenciar la tarea,
        # así que enviamos el texto crudo, sin prefijos manuales.
        contents = [it["text"] for it in batch]
        try:
            resp = client.models.embed_content(
                model=embedding_model,
                contents=contents,
                config=config,
            )
        except Exception as e:
            # El lote falla → esos chunks no se marcan 'ready'. La próxima corrida los
            # vuelve a tomar (borra sus embeddings parciales y reintenta). Idempotente.
            logger.error("Error embeibiendo un lote de %s texto(s): %s", len(batch), e)
            continue

        if len(resp.embeddings) != len(batch):
            logger.error(
                "Desajuste: %s embeddings para %s textos enviados; se omite el lote.",
                len(resp.embeddings), len(batch),
            )
            continue

        done_ids: list[int] = []
        for it, sent_text, emb in zip(batch, contents, resp.embeddings):
            tokens = _token_count(emb, sent_text, tokenizer)
            if tokens <= 5:
                logger.warning("Sub chunk del chunk id=%s con muy pocos tokens (%s).", it["summary_id"], tokens)
            session.add(models.DiscordChunkEmbeddings(
                summary_id=it["summary_id"],
                chunk=it["text"],
                embedding=emb.values,
                input_tokens=tokens,
                embedding_model=embedding_model,
            ))
            remaining[it["summary_id"]] -= 1
            if remaining[it["summary_id"]] == 0:
                done_ids.append(it["summary_id"])

        # Marcamos 'ready' los chunks que completaron todos sus sub-embeddings en este
        # lote, en el mismo commit que sus embeddings.
        if done_ids:
            session.query(models.DiscordSummaryStatus).filter(
                models.DiscordSummaryStatus.summary_id.in_(done_ids)
            ).update({models.DiscordSummaryStatus.naive_rag_status: "ready"}, synchronize_session=False)
            total_done += len(done_ids)

        session.commit()
        logger.info("Lote OK: %s texto(s); %s chunk(s) completados acumulados.", len(batch), total_done)

    logger.info("Terminado: %s/%s chunk(s) marcados 'ready'.", total_done, len(records))


if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src import settings
    from src.logging_config import setup_base_logging

    setup_base_logging()

    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING)
    MySession = sessionmaker(bind=engine)
    session = MySession()

    client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    model = "gemini-embedding-001"

    # Tokenizer local de fallback (mismo vocab que Gemini; mirror sin gating). Solo se
    # usa si la API no devolviera statistics.token_count.
    tokenizer = Tokenizer.from_pretrained("unsloth/gemma-2-2b")

    make_text_embeddings_batch(
        session=session,
        client=client,
        embedding_model=model,
        tokenizer=tokenizer,
    )


"""
python3 -m src.services.v1.NaiveRag.make_text_embeddings_batch


"""