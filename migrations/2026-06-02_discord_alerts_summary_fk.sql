-- Migración: tabla discord_alerts
--   Formaliza la relación con discord_chronological_summary mediante una FK
--   summary_id con ON DELETE CASCADE (antes el vínculo era implícito vía
--   channel_id+start_time). Resuelve las alertas huérfanas al borrar un chunk.
--
-- Fecha: 2026-06-02
-- Idempotente y transaccional.
--
-- Ejecutar (misma conexión que src/settings.DB_DISCORD_CONN_STRING):
--   psql "postgresql://<user>:<pass>@<host>:<port>/<db_discord>" \
--        -f migrations/2026-06-02_discord_alerts_summary_fk.sql

BEGIN;

-- 1) Añadir la columna nullable (para poder backfilear los registros existentes).
ALTER TABLE discord_alerts
    ADD COLUMN IF NOT EXISTS summary_id integer;

-- 2) Backfill: enlazar cada alerta con su chunk por (channel_id, start_time),
--    que es la clave implícita con la que se venían guardando.
UPDATE discord_alerts a
SET summary_id = s.id
FROM discord_chronological_summary s
WHERE a.summary_id IS NULL
  AND s.channel_id = a.channel_id
  AND s.start_time = a.start_time;

-- 3) Crear la FK con ON DELETE CASCADE (solo si no existe).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_discord_alerts_summary'
    ) THEN
        ALTER TABLE discord_alerts
            ADD CONSTRAINT fk_discord_alerts_summary
            FOREIGN KEY (summary_id)
            REFERENCES discord_chronological_summary (id)
            ON DELETE CASCADE;
    END IF;
END$$;

-- 4) Índice para la FK.
CREATE INDEX IF NOT EXISTS ix_discord_alerts_summary_id
    ON discord_alerts (summary_id);

-- 5) Forzar NOT NULL. Si esto FALLA es porque quedaron alertas que no se pudieron
--    enlazar a ningún chunk (huérfanas); toda la transacción se revierte. En ese
--    caso revísalas (SELECT * FROM discord_alerts WHERE summary_id IS NULL) y
--    decide si borrarlas antes de reintentar.
ALTER TABLE discord_alerts
    ALTER COLUMN summary_id SET NOT NULL;

COMMIT;
