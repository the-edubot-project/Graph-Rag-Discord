from lightrag import LightRAG
from lightrag.utils import EmbeddingFunc, TokenTracker, TiktokenTokenizer
from lightrag.llm.gemini import gemini_embed
from lightrag.llm.openai import openai_complete
from . import conf
from src import settings
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

os.environ["GEMINI_API_KEY"] = settings.GOOGLE_API_KEY




_rag: LightRAG | None = None

# Acumuladores globales de tokens. Se leen por delta (snapshot antes/después de
# cada inserción) desde incert_to_lightrag.py para atribuir el consumo a cada
# summary_id. NO se pasan dentro de llm_model_kwargs: LightRAG hace asdict()/
# deepcopy de esos campos y perdería la referencia al tracker.
llm_tracker = TokenTracker()
embed_tracker = TokenTracker()

# La API de embeddings de Gemini no reporta usage de forma fiable, así que los
# tokens de embedding se cuentan localmente (aproximados) con tiktoken.
_embed_tokenizer = TiktokenTokenizer()


async def _llm_model_func(prompt, **kwargs):
    # Inyecta el tracker en cada llamada; openai_complete -> openai_complete_if_cache
    # lo usa para registrar response.usage (prompt/completion/total) de vLLM.
    kwargs["token_tracker"] = llm_tracker
    return await openai_complete(prompt, **kwargs)


async def _embedding_func(texts, **kwargs):
    n_tokens = sum(len(_embed_tokenizer.encode(t)) for t in texts)
    embed_tracker.add_usage({"prompt_tokens": n_tokens, "total_tokens": n_tokens})
    return await gemini_embed.func(texts, **kwargs)


async def _get_rag() -> LightRAG:
    global _rag
    if _rag is None:
        gemini_embedding = EmbeddingFunc(
            embedding_dim=conf.EMBED_DIM,
            max_token_size=8000,
            model_name=conf.EMBED_MODEL,
            send_dimensions=True,
            func=_embedding_func,
        )
        _rag = LightRAG(
            working_dir=str(settings.ROOT / "data" / "rag_storage"),
            llm_model_func=_llm_model_func,
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


