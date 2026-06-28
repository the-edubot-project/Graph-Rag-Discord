-- Migración: tablas de consumo de tokens
--   1) graphiti_token_usage  -> modelo dmodels.GraphitiTokenUsage
--   2) lightrag_token_usage   -> modelo dmodels.LightragTokenUsage
--
-- Ambas registran DOS filas por summary_id procesado (kind='llm' / 'embedding'):
--   input_tokens / output_tokens en tokens; embed_calls = nº de textos embebidos
--   (solo relevante para kind='embedding'). El DDL es equivalente al que
--   generaría SQLAlchemy con Base.metadata.create_all() desde src/discord_models.py.
--
-- Fecha: 2026-06-28
-- Idempotente y transaccional: se puede ejecutar más de una vez sin error.
--
-- Ejecutar contra la base donde viven los modelos (la de LightRAG/Graphiti, es
-- decir settings.THE_EDUBOT_DB_CONN_STRING):
--   psql "postgresql://<user>:<pass>@<host>:<port>/<db>" \
--        -f migrations/2026-06-28_token_usage_tables.sql

BEGIN;

-- 1) graphiti_token_usage
CREATE TABLE IF NOT EXISTS graphiti_token_usage (
    id            SERIAL PRIMARY KEY,
    summary_id    INTEGER       NOT NULL,
    channel_id    BIGINT,
    kind          VARCHAR(16)   NOT NULL,   -- 'llm' | 'embedding'
    model_name    VARCHAR(255)  NOT NULL,
    input_tokens  INTEGER       NOT NULL DEFAULT 0,
    output_tokens INTEGER       NOT NULL DEFAULT 0,
    embed_calls   INTEGER,
    created_at    TIMESTAMP              DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_graphiti_token_usage_summary_id
    ON graphiti_token_usage (summary_id);
CREATE INDEX IF NOT EXISTS ix_graphiti_token_usage_channel_id
    ON graphiti_token_usage (channel_id);

-- 2) lightrag_token_usage
CREATE TABLE IF NOT EXISTS lightrag_token_usage (
    id            SERIAL PRIMARY KEY,
    summary_id    INTEGER       NOT NULL,
    channel_id    BIGINT,
    kind          VARCHAR(16)   NOT NULL,   -- 'llm' | 'embedding'
    model_name    VARCHAR(255)  NOT NULL,
    input_tokens  INTEGER       NOT NULL DEFAULT 0,
    output_tokens INTEGER       NOT NULL DEFAULT 0,
    embed_calls   INTEGER,
    created_at    TIMESTAMP              DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_lightrag_token_usage_summary_id
    ON lightrag_token_usage (summary_id);
CREATE INDEX IF NOT EXISTS ix_lightrag_token_usage_channel_id
    ON lightrag_token_usage (channel_id);

COMMIT;
