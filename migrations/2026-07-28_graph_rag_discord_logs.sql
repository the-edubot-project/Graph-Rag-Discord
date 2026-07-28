-- Migración: tabla de logs de la aplicación
--   graph_rag_discord_logs -> modelo log_models.GraphRagDiscordLog
--
-- Una fila por registro de logging emitido por los servicios de producción
-- (DiscordSumaries y NaiveRag), escrita por PostgresLogHandler
-- (src/logging_config.py, activado con get_logger(..., to_db=True)):
--   level        'INFO' | 'WARNING' | 'ERROR'
--   content      mensaje del log (traceback incluido si venía con exc_info)
--   script_path  ruta del script emisor, relativa a la raíz del repo
--   inserted_at  fecha/hora de inserción (default now())
-- El DDL es equivalente al que generaría SQLAlchemy con
-- LogBase.metadata.create_all() desde src/log_models.py.
--
-- Fecha: 2026-07-28
-- Idempotente y transaccional: se puede ejecutar más de una vez sin error.
--
-- Ejecutar contra la base donde viven los modelos (settings.THE_EDUBOT_DB_CONN_STRING):
--   psql "postgresql://<user>:<pass>@<host>:<port>/<db>" \
--        -f migrations/2026-07-28_graph_rag_discord_logs.sql

BEGIN;

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

COMMIT;
