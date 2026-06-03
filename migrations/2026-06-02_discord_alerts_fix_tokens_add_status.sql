-- Migración: tabla discord_alerts
--   1) Corrige el typo de columna  input_tokes -> input_tokens
--   2) Crea el enum  alert_status  y añade la columna del mismo nombre
--      (estado de procesamiento downstream: 'pending' -> 'sent' -> 'ready')
--
-- Fecha: 2026-06-02
-- Idempotente y transaccional: se puede ejecutar más de una vez sin error.
--
-- Ejecutar (usa la misma conexión que src/settings.DB_DISCORD_CONN_STRING):
--   psql "postgresql://<user>:<pass>@<host>:<port>/<db_discord>" \
--        -f migrations/2026-06-02_discord_alerts_fix_tokens_add_status.sql

BEGIN;

-- 1) Renombrar input_tokes -> input_tokens (solo si aún existe el nombre viejo
--    y no existe ya el nuevo).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'discord_alerts' AND column_name = 'input_tokes'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'discord_alerts' AND column_name = 'input_tokens'
    ) THEN
        ALTER TABLE discord_alerts RENAME COLUMN input_tokes TO input_tokens;
    END IF;
END$$;

-- 2) Crear el tipo enum alert_status si no existe.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'alert_status') THEN
        CREATE TYPE alert_status AS ENUM ('pending', 'sent', 'ready');
    END IF;
END$$;

-- 3) Añadir la columna alert_status (NOT NULL, default 'pending').
ALTER TABLE discord_alerts
    ADD COLUMN IF NOT EXISTS alert_status alert_status NOT NULL DEFAULT 'pending';

COMMIT;
