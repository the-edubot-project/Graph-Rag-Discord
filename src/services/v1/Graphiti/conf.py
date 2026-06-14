from src import settings

# LLM: servidor vLLM (OpenAI-compatible), el mismo que usa el servicio LightRag.
VLLM_BASE_URL = settings.VLLM_BASE_URL
LLM_MODEL = "gemma-4-26b"

# Embeddings: Gemini (Google). Graphiti guarda los embeddings en el índice
# vectorial de Neo4j, NO en Postgres.
GOOGLE_API_KEY = settings.GOOGLE_API_KEY
EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 1536

# Modo de salida estructurada del LLM:
#   - "json_schema": decodificación guiada nativa (ideal si tu vLLM soporta
#     guided_json / outlines). Da extracciones más fiables.
#   - "json_object": fallback por prompt para endpoints que no soportan json_schema.
# Si la ingesta falla por errores de parseo JSON, cambia a "json_object".
STRUCTURED_OUTPUT_MODE = "json_schema"

# Particionamos el grafo por canal de Discord usando el group_id de Graphiti.
# Esto permite acotar búsquedas a un canal concreto y mantiene la continuidad
# temporal de episodios por canal.
def group_id_for_channel(channel_id: int) -> str:
    return f"channel_{channel_id}"
