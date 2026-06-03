-- Migración: tabla discord_chronological_summary
--   Añade el marcador de cobertura de alertas  alerts_done  (boolean).
--   True  = ya se extrajeron alertas para el contenido actual del chunk (aunque 0).
--   False = pendiente (chunk nuevo, o reabierto/cambiado por el pipeline de chunking).
--
-- Fecha: 2026-06-02
-- Idempotente y transaccional.
--
-- Ejecutar (misma conexión que src/settings.DB_DISCORD_CONN_STRING):
--   psql "postgresql://<user>:<pass>@<host>:<port>/<db_discord>" \
--        -f migrations/2026-06-02_chunk_alerts_done.sql

BEGIN;

ALTER TABLE discord_chronological_summary
    ADD COLUMN IF NOT EXISTS alerts_done boolean NOT NULL DEFAULT false;

COMMIT;
