from src import settings

# LLM: vLLM server (gemma-4-26b, OpenAI-compatible)
VLLM_BASE_URL = settings.VLLM_BASE_URL
LLM_MODEL = "gemma-4-26b"

# Embeddings: Gemini (se mantiene para no re-indexar los vectores existentes)
EMBED_DIM = 1536
EMBED_MODEL = "gemini-embedding-001"


