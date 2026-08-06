"""
Router v1 que expone como API el pipeline de resúmenes cronológicos de Discord.

Tres endpoints, uno por cada paso del pipeline (ver
src/services/v1/DiscordSumaries/main.py):

  POST /v1/discord-summaries/rechunk        → rechunk_all_available_channels
  POST /v1/discord-summaries/mark-mature    → seed_mature_status
  POST /v1/discord-summaries/summaries      → make_all_pending_summaries

Y un endpoint de conveniencia que los encadena en orden:

  POST /v1/discord-summaries/pipeline       → los tres pasos, secuencialmente
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src import settings
from src.api.deps import get_session
from src.services.v1.DiscordSumaries.chunking import rechunk_all_available_channels
from src.services.v1.DiscordSumaries.force_merge import force_merge_with_previous
from src.services.v1.DiscordSumaries.mark_mature import seed_mature_status
from src.services.v1.DiscordSumaries.summary_chunks import make_all_pending_summaries

router = APIRouter(prefix="/discord-summaries", tags=["discord-summaries"])


class SummariesRequest(BaseModel):
    """Parámetros del paso de resumen (paso 3)."""

    model: str = Field(
        default="gemini-2.5-flash", description="Modelo LLM (Google) a usar."
    )
    concurrency: int = Field(
        default=4, ge=1, le=32, description="Tareas LLM concurrentes (tamaño del semáforo)."
    )
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class StepResponse(BaseModel):
    status: str = "ok"
    step: str
    detail: Optional[str] = None


class MergeResponse(BaseModel):
    status: str = "ok"
    step: str = "force-merge"
    chunk_id: int
    merged: bool
    detail: Optional[str] = None


def _build_llm(req: SummariesRequest):
    """Construye el ChatModel para el paso de resumen (Google / GOOGLE_API_KEY)."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=req.model,
        temperature=req.temperature,
        api_key=settings.GOOGLE_API_KEY,
    )


async def _run_summaries(session: Session, req: SummariesRequest) -> None:
    semaphore = asyncio.Semaphore(req.concurrency)
    llm = _build_llm(req)
    await make_all_pending_summaries(
        session=session, semaphore=semaphore, llm=llm, llm_model=req.model
    )


# ──────────────────────────── endpoints ────────────────────────────


@router.post("/rechunk", response_model=StepResponse)
def rechunk(session: Session = Depends(get_session)) -> StepResponse:
    """Paso 1: divide en chunks semanales los mensajes aún no chunkenizados."""
    rechunk_all_available_channels(session=session)
    return StepResponse(step="rechunk", detail="Canales re-chunkenizados.")


@router.post("/mark-mature", response_model=StepResponse)
def mark_mature(session: Session = Depends(get_session)) -> StepResponse:
    """Paso 2: marca como maduros (inmutables) los chunks que cumplen la política."""
    seed_mature_status(session=session)
    return StepResponse(step="mark-mature", detail="Chunks maduros marcados.")


@router.post("/force-merge/{chunk_id}", response_model=MergeResponse)
def force_merge(
    chunk_id: int, session: Session = Depends(get_session)
) -> MergeResponse:
    """
    Fusiona un chunk (vivo) con el chunk inmediatamente anterior del mismo canal.

    Devuelve `merged=False` si no se pudo mergear (chunk inexistente, sin
    predecesor, o con referencias downstream que requieren limpieza previa);
    revisa los logs de force_merge para el motivo concreto.
    """
    merged = force_merge_with_previous(session=session, chunk_id=chunk_id)
    detail = (
        f"Chunk {chunk_id} fusionado con su predecesor."
        if merged
        else f"No se fusionó el chunk {chunk_id} (ver logs para el motivo)."
    )
    return MergeResponse(chunk_id=chunk_id, merged=merged, detail=detail)


@router.post("/summaries", response_model=StepResponse)
async def summaries(
    req: SummariesRequest = SummariesRequest(),
    session: Session = Depends(get_session),
) -> StepResponse:
    """Paso 3: genera (o regenera) los resúmenes de los chunks pendientes."""
    await _run_summaries(session, req)
    return StepResponse(step="summaries", detail=f"Resúmenes generados con {req.model}.")


@router.post("/pipeline", response_model=StepResponse)
async def pipeline(
    req: SummariesRequest = SummariesRequest(),
    session: Session = Depends(get_session),
) -> StepResponse:
    """Conveniencia: ejecuta los tres pasos en orden (rechunk → mark-mature → summaries)."""
    # Los pasos 1 y 2 son síncronos y bloqueantes; los corremos en un hilo para no
    # bloquear el event loop.
    await asyncio.to_thread(rechunk_all_available_channels, session=session)
    await asyncio.to_thread(seed_mature_status, session=session)
    await _run_summaries(session, req)
    return StepResponse(step="pipeline", detail="Pipeline completo ejecutado.")
