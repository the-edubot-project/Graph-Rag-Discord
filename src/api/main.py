"""
Punto de entrada de la API (FastAPI).

Crea la app y registra los routers de cada versión. Toda la lógica de negocio vive
en src/services/...; aquí solo se exponen los endpoints.

Levantar en local:
    .venv/bin/uvicorn src.api.main:app --reload
"""

from fastapi import FastAPI

from src.api.v1.routers import discord_summaries, naive_rag
from src.logging_config import setup_base_logging

setup_base_logging()

app = FastAPI(
    title="Graph-Rag-Discord API",
    description="API para el pipeline de procesamiento y resumen de mensajes de Discord.",
    version="1.0.0",
)

# Routers v1
app.include_router(discord_summaries.router, prefix="/v1")
app.include_router(naive_rag.router, prefix="/v1")


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok"}
