from lightrag import LightRAG
from lightrag.utils import EmbeddingFunc
from lightrag.llm.gemini import gemini_embed
from lightrag.llm.openai import openai_complete
from . import conf
import settings
import os

# LightRAG lee credenciales de os.environ, no de variables Python.
os.environ["POSTGRES_HOST"] = settings.DB_HOST
os.environ["POSTGRES_PORT"] = str(settings.DB_PORT)
os.environ["POSTGRES_USER"] = settings.DB_USER
os.environ["POSTGRES_PASSWORD"] = settings.DB_PASS
os.environ["POSTGRES_DATABASE"] = settings.DB_NAME

os.environ["NEO4J_URI"] = settings.NEO4J_URI
os.environ["NEO4J_USERNAME"] = settings.NEO4J_USERNAME
os.environ["NEO4J_PASSWORD"] = settings.NEO4J_PASSWORD



_rag: LightRAG | None = None


async def _get_rag() -> LightRAG:
    global _rag
    if _rag is None:
        gemini_embedding = EmbeddingFunc(
            embedding_dim=conf.EMBED_DIM,
            max_token_size=8000,
            model_name=conf.EMBED_MODEL,
            send_dimensions=True,
            func=gemini_embed.func,
        )
        _rag = LightRAG(
            working_dir=str(settings.ROOT / "data" / "rag_storage"),
            llm_model_func=openai_complete,
            llm_model_name=conf.LLM_MODEL,
            llm_model_kwargs={
                "base_url": conf.VLLM_BASE_URL,
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


