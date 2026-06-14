"""
Router v1 que expone el pipeline de embeddings de NaiveRag.

  POST /v1/naive-rag/embeddings  → make_text_embeddings_batch

Embebe (en batch, vía google-genai) todos los chunks pendientes
(naive_rag_status IS NULL y summary != NULL) y los marca 'ready'.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src import settings
from src.api.deps import get_session
from src.services.v1.NaiveRag import conf
from src.services.v1.NaiveRag.make_text_embeddings_google import make_text_embeddings_batch

router = APIRouter(prefix="/naive-rag", tags=["naive-rag"])

# Tokenizer local de fallback (mismo vocab que Gemini). Solo se usa si la API no
# devolviera statistics.token_count. Cacheado a nivel de módulo para no re-descargarlo
# en cada request.
_TOKENIZER = None


def _get_tokenizer():
    global _TOKENIZER
    if _TOKENIZER is None:
        from tokenizers import Tokenizer

        _TOKENIZER = Tokenizer.from_pretrained("unsloth/gemma-2-2b")
    return _TOKENIZER


class EmbeddingsRequest(BaseModel):
    """Parámetros del paso de embeddings."""

    embedding_model: str = Field(default="gemini-embedding-001")
    batch_size: int = Field(default=conf.GOOGLE_EMBEDDING_BATCH_SIZE, ge=1, le=250)
    output_dimensionality: int = Field(default=conf.GOOGLE_EMBEDDING_OUTPUT_DIM, ge=1)
    task_type: str = Field(default="RETRIEVAL_DOCUMENT")
    use_tokenizer_fallback: bool = Field(
        default=False,
        description=(
            "Carga un tokenizer local (Gemma) como fallback de conteo de tokens. "
            "Normalmente innecesario: la API de Google ya devuelve token_count."
        ),
    )


class EmbeddingsResponse(BaseModel):
    status: str = "ok"
    step: str = "embeddings"
    detail: Optional[str] = None


@router.post("/embeddings", response_model=EmbeddingsResponse)
def embeddings(
    req: EmbeddingsRequest = EmbeddingsRequest(),
    session: Session = Depends(get_session),
) -> EmbeddingsResponse:
    """Genera los embeddings de todos los chunks pendientes (naive_rag_status IS NULL)."""
    from google import genai

    client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    tokenizer = _get_tokenizer() if req.use_tokenizer_fallback else None

    make_text_embeddings_batch(
        session=session,
        client=client,
        embedding_model=req.embedding_model,
        task_type=req.task_type,
        output_dimensionality=req.output_dimensionality,
        batch_size=req.batch_size,
        tokenizer=tokenizer,
    )
    return EmbeddingsResponse(detail=f"Embeddings generados con {req.embedding_model}.")
