"""
Construye (y cachea) una instancia de Graphiti configurada con:
  - LLM   -> vLLM vía OpenAIGenericClient (endpoint OpenAI-compatible).
  - Embed -> Gemini (gemini-embedding-001) vía GeminiEmbedder.
  - Grafo -> Neo4j (el mismo que usa el servicio LightRag).

Análogo a LightRag/get_lightrag_vllm_googleEmb.py, pero para Graphiti.

NOTA sobre Neo4j: Graphiti escribe en Neo4j con sus propias etiquetas
(Entity / Episodic / Community), distintas de las que crea LightRAG, por lo que
pueden convivir en la misma base. Aun así, si quieres aislarlos por completo,
usa una base/instancia de Neo4j dedicada para Graphiti.
"""

from graphiti_core import Graphiti
from graphiti_core.llm_client import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

from src import settings
from . import conf

_graphiti: Graphiti | None = None


async def _get_graphiti() -> Graphiti:
    global _graphiti
    if _graphiti is None:
        # Config LLM compartida (la reutiliza también el reranker).
        llm_config = LLMConfig(
            api_key="EMPTY",            # vLLM no requiere auth real
            base_url=conf.VLLM_BASE_URL,
            model=conf.LLM_MODEL,
            small_model=conf.LLM_MODEL,  # vLLM sirve un solo modelo
        )

        llm_client = OpenAIGenericClient(
            config=llm_config,
            structured_output_mode=conf.STRUCTURED_OUTPUT_MODE,
            max_tokens=conf.LLM_MAX_TOKENS,
        )

        embedder = GeminiEmbedder(
            config=GeminiEmbedderConfig(
                api_key=conf.GOOGLE_API_KEY,
                embedding_model=conf.EMBED_MODEL,
                embedding_dim=conf.EMBED_DIM,
            )
        )

        # El cross-encoder por defecto (OpenAIRerankerClient sin config) apunta a
        # la API de OpenAI; lo redirigimos al endpoint vLLM. Usa logprobs del
        # /chat/completions, que vLLM soporta.
        cross_encoder = OpenAIRerankerClient(config=llm_config)

        graphiti = Graphiti(
            settings.NEO4J_URI,
            settings.NEO4J_USERNAME,
            settings.NEO4J_PASSWORD,
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=cross_encoder,
        )

        # Idempotente: crea índices y constraints (incluido el índice vectorial)
        # si no existen todavía.
        await graphiti.build_indices_and_constraints()

        _graphiti = graphiti

    return _graphiti
