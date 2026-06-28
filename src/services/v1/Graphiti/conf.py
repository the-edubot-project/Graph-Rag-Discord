from src import settings

# LLM: servidor vLLM (OpenAI-compatible), el mismo que usa el servicio LightRag.
VLLM_BASE_URL = settings.VLLM_BASE_URL
LLM_MODEL = "gemma-4-26b"

# Embeddings: Gemini (Google). Graphiti guarda los embeddings en el índice
# vectorial de Neo4j, NO en Postgres.
GOOGLE_API_KEY = settings.GOOGLE_API_KEY
EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 1536

# Tope de tokens de SALIDA por llamada al LLM.
# OJO: esto NO recorta lo que Graphiti procesa. El resumen y el contexto viajan
# en el PROMPT (la entrada); max_tokens solo limita el largo de la RESPUESTA
# generada. Por defecto OpenAIGenericClient pide 16384 de salida, lo que sumado
# a prompts grandes (la dedup puede mandar ~16K tokens) supera la ventana de
# 32768 -> vLLM responde 400. Para extracción/dedup la respuesta es una lista de
# entidades o un mapeo JSON corto, así que 4096 sobra y deja ~28K para el prompt.
LLM_MAX_TOKENS = 4096

# Modo de salida estructurada del LLM:
#   - "json_schema": decodificación guiada nativa (ideal si tu vLLM soporta
#     guided_json / outlines). Da extracciones más fiables.
#   - "json_object": fallback por prompt para endpoints que no soportan json_schema.
# Si la ingesta falla por errores de parseo JSON, cambia a "json_object".
STRUCTURED_OUTPUT_MODE = "json_schema"

# Nº de CANALES que se ingieren en paralelo. Dentro de cada canal los episodios
# van secuenciales y en orden cronológico (la dedup y previous_episode_uuids lo
# exigen); el paralelismo es ENTRE canales distintos, que es seguro porque
# Graphiti deduplica entidades por group_id.
#
# vLLM es UNA instancia con continuous batching: atiende varias peticiones a la
# vez sin abrir más procesos ni cargar más modelos.
#
# OJO: lo bajamos a 1 a propósito. Al subir la ventana de contexto a 49152 (ver
# vLLM-serving/docker-compose.yaml), cada petición larga consume mucho más
# KV-cache. Además, CADA add_episode ya dispara internamente varias llamadas LLM
# en paralelo (extracción/dedup/atributos vía semaphore_gather de graphiti), así
# que aunque procesemos 1 canal a la vez, vLLM igual recibe ráfagas concurrentes.
# Con CONCURRENCY>1 esas ráfagas (incluida la de extract_edges, 16384 de salida)
# saturan el pool y se preempten -> lento e inestable. 1 prioriza fiabilidad.
# Si tras subir el contexto ves las GPUs infrautilizadas, prueba 2.
CONCURRENCY = 1

# Reintentos ante errores TRANSITORIOS de las APIs (503/429/5xx, timeouts) del
# LLM o del embedder Gemini. Se reintenta el episodio completo EN SITIO (preserva
# el orden cronológico del canal) con backoff exponencial; agotados los intentos
# el chunk se marca fallido y se reintenta en la próxima ejecución.
MAX_RETRIES = 4
RETRY_BACKOFF = 2.0  # segundos base; espera = RETRY_BACKOFF * 2**(intento-1)

# Particionamos el grafo por canal de Discord usando el group_id de Graphiti.
# Esto permite acotar búsquedas a un canal concreto y mantiene la continuidad
# temporal de episodios por canal.
def group_id_for_channel(channel_id: int) -> str:
    return f"channel_{channel_id}"
