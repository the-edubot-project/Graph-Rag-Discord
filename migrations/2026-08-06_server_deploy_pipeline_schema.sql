-- Migración: esquema mínimo que necesita el pipeline diario (src/pipeline.py)
-- para correr en el servidor de producción.
--
-- Contexto: la BD del servidor (the_edubot_db) se creó antes de varios cambios de
-- modelo y le falta al menos `graph_rag_discord_logs`. Este script consolida, en un
-- solo fichero, todo lo que los 5 pasos del pipeline escriben:
--
--   1. rechunk_all_available_channels  -> discord_chronological_summary (status,
--                                         alerts_done), discord_summary_state
--   2. seed_mature_status              -> discord_chronological_summary.status
--   3. make_all_pending_summaries      -> discord_chronological_summary
--                                         (summary, input_tokens, output_tokens, model)
--   4. make_text_embeddings_batch      -> discord_chunk_embeddings,
--                                         discord_summary_state.naive_rag_status
--   5. summary_text_channels           -> discord_channel_context
--   (transversal) logging a BD         -> graph_rag_discord_logs
--
-- NO incluye graphiti_token_usage / lightrag_token_usage: esas pertenecen a
-- migrations/2026-06-28_token_usage_tables.sql y solo hacen falta cuando se
-- despliegue la ingesta de Graphiti/LightRAG, que no forma parte del pipeline.
--
-- Fecha: 2026-08-06
-- Idempotente y transaccional: se puede ejecutar más de una vez sin error, y sobre
-- una BD que ya tenga parte (o todo) el esquema. No modifica ni borra datos.
-- Requiere PostgreSQL 12+ (usa ADD COLUMN / ADD VALUE ... IF NOT EXISTS).
--
-- Ejecutar contra la base de settings.THE_EDUBOT_DB_CONN_STRING:
--   psql "postgresql://<user>:<pass>@<host>:<port>/<db>" \
--        -f migrations/2026-08-06_server_deploy_pipeline_schema.sql
--
-- En el servidor, con la BD en Docker:
--   docker exec -i the-edubot-project-db psql -U postgres -d the_edubot_db \
--       < migrations/2026-08-06_server_deploy_pipeline_schema.sql

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- 0) Preflight + extensión pgvector (la necesita discord_chunk_embeddings).
--
-- Este script parchea una BD que ya tiene el esquema base de Discord (es el caso
-- del servidor). Si se ejecuta contra una BD vacía, los ALTER TABLE fallarían con
-- un error poco claro; mejor abortar de entrada con un mensaje explícito.
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(t, ', ')
      INTO missing
      FROM (VALUES ('discord_channels'), ('discord_chronological_summary')) AS v(t)
     WHERE to_regclass(t) IS NULL;

    IF missing IS NOT NULL THEN
        RAISE EXCEPTION
            'Faltan tablas base (%). Esta migración parchea una BD con el esquema '
            'de Discord ya creado; créalo primero.', missing;
    END IF;
END
$$;

CREATE EXTENSION IF NOT EXISTS vector;


-- ─────────────────────────────────────────────────────────────────────────────
-- 1) graph_rag_discord_logs  -> src/log_models.py:GraphRagDiscordLog
--
-- Escrita por PostgresLogHandler (src/logging_config.py) para los loggers creados
-- con get_logger(..., to_db=True). Sin esta tabla el proceso no rompe (el handler
-- se autodesactiva tras N fallos), pero se pierden los logs en BD.
-- Mismo DDL que migrations/2026-07-28_graph_rag_discord_logs.sql; se repite aquí
-- para que este fichero baste por sí solo en un despliegue nuevo.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS graph_rag_discord_logs (
    id           SERIAL PRIMARY KEY,
    level        VARCHAR(16) NOT NULL,   -- 'INFO' | 'WARNING' | 'ERROR'
    content      TEXT        NOT NULL,
    script_path  TEXT,
    inserted_at  TIMESTAMP            DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_graph_rag_discord_logs_level
    ON graph_rag_discord_logs (level);
CREATE INDEX IF NOT EXISTS ix_graph_rag_discord_logs_script_path
    ON graph_rag_discord_logs (script_path);
CREATE INDEX IF NOT EXISTS ix_graph_rag_discord_logs_inserted_at
    ON graph_rag_discord_logs (inserted_at);


-- ─────────────────────────────────────────────────────────────────────────────
-- 2) discord_chronological_summary: columnas que escriben los pasos 1, 2 y 3.
--
--   status       Boolean  - NULL/False = chunk "vivo" (re-chunkenizable),
--                           True = maduro/inmutable (mark_mature.py, chunking.py).
--                           Se deja NULLable a propósito: el modelo no fija default
--                           y chunking.py inserta status=False explícitamente.
--   alerts_done  Boolean  - NOT NULL DEFAULT false; lo invalidan chunking.py y
--                           force_merge.py cuando el contenido del chunk cambia.
--   input_tokens / output_tokens / model - consumo del LLM de resumen
--                           (summary_chunks.py, ahora gemini-2.5-flash).
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE discord_chronological_summary
    ADD COLUMN IF NOT EXISTS status        BOOLEAN,
    ADD COLUMN IF NOT EXISTS alerts_done   BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS input_tokens  INTEGER,
    ADD COLUMN IF NOT EXISTS output_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS model         VARCHAR,
    ADD COLUMN IF NOT EXISTS inserted_at   TIMESTAMP DEFAULT now();


-- ─────────────────────────────────────────────────────────────────────────────
-- 3) Enum summary_status + discord_summary_state.
--
-- Ojo: los tres campos de estado comparten un único tipo enum llamado
-- summary_status, pero cada modelo declara solo el subconjunto de etiquetas que
-- usa ('in_lightrag'/'ready', 'embeded'/'ready', 'in_graphiti'/'ready'). Por eso
-- el tipo en BD debe contener la UNIÓN de las cuatro etiquetas; si falta alguna,
-- el UPDATE correspondiente falla con "invalid input value for enum".
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'summary_status') THEN
        CREATE TYPE summary_status AS ENUM (
            'ready', 'embeded', 'in_lightrag', 'in_graphiti'
        );
    END IF;
END
$$;

-- Completa las etiquetas que falten si el tipo ya existía con menos valores.
-- (PG 12+: ADD VALUE es válido dentro de una transacción siempre que el valor
--  nuevo no se USE en la misma transacción; aquí solo se declara.)
ALTER TYPE summary_status ADD VALUE IF NOT EXISTS 'ready';
ALTER TYPE summary_status ADD VALUE IF NOT EXISTS 'embeded';
ALTER TYPE summary_status ADD VALUE IF NOT EXISTS 'in_lightrag';
ALTER TYPE summary_status ADD VALUE IF NOT EXISTS 'in_graphiti';

CREATE TABLE IF NOT EXISTS discord_summary_state (
    summary_id       INTEGER PRIMARY KEY
                     REFERENCES discord_chronological_summary (id),
    lightrag_status  summary_status,
    naive_rag_status summary_status,
    graphiti_status  summary_status
);

ALTER TABLE discord_summary_state
    ADD COLUMN IF NOT EXISTS lightrag_status  summary_status,
    ADD COLUMN IF NOT EXISTS naive_rag_status summary_status,
    ADD COLUMN IF NOT EXISTS graphiti_status  summary_status;


-- ─────────────────────────────────────────────────────────────────────────────
-- 4) discord_chunk_embeddings: destino del paso 4 (NaiveRag con Google).
--
-- La dimensión 3072 viene de conf.GOOGLE_EMBEDDING_OUTPUT_DIM
-- (src/services/v1/NaiveRag/conf.py) con el modelo gemini-embedding-001.
-- Si la tabla ya existe con otra dimensión, este script NO la cambia: hay que
-- decidir a mano qué hacer con los vectores existentes.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS discord_chunk_embeddings (
    id              SERIAL PRIMARY KEY,
    summary_id      INTEGER REFERENCES discord_chronological_summary (id),
    chunk           TEXT,
    embedding       VECTOR(3072),
    input_tokens    INTEGER,
    embedding_model VARCHAR,
    inserted_at     TIMESTAMP DEFAULT now()
);

ALTER TABLE discord_chunk_embeddings
    ADD COLUMN IF NOT EXISTS input_tokens    INTEGER,
    ADD COLUMN IF NOT EXISTS embedding_model VARCHAR,
    ADD COLUMN IF NOT EXISTS inserted_at     TIMESTAMP DEFAULT now();

CREATE INDEX IF NOT EXISTS ix_discord_chunk_embeddings_summary_id
    ON discord_chunk_embeddings (summary_id);


-- ─────────────────────────────────────────────────────────────────────────────
-- 5) discord_channel_context: destino del paso 5 (contexto de canales de texto).
--
-- El paso 5 consulta esta tabla para saltarse los canales ya procesados
-- (ChannelContext/text_channels.py), así que es incremental por diseño.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS discord_channel_context (
    id              SERIAL PRIMARY KEY,
    channel_id      BIGINT REFERENCES discord_channels (id),
    summary_context TEXT
);

CREATE INDEX IF NOT EXISTS ix_discord_channel_context_channel_id
    ON discord_channel_context (channel_id);

COMMIT;


-- ─────────────────────────────────────────────────────────────────────────────
-- Verificación post-migración (ejecutar aparte):
--
--   \d graph_rag_discord_logs
--   \d discord_chronological_summary
--   \d discord_summary_state
--   \d discord_chunk_embeddings
--   \d discord_channel_context
--
--   SELECT enumlabel FROM pg_enum e
--     JOIN pg_type t ON t.oid = e.enumtypid
--    WHERE t.typname = 'summary_status' ORDER BY enumsortorder;
--   -- esperado: ready, embeded, in_lightrag, in_graphiti (en cualquier orden)
-- ─────────────────────────────────────────────────────────────────────────────
