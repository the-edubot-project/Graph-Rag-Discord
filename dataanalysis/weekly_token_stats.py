"""
Análisis exploratorio: tokens aproximados y número de mensajes por semana/canal.

Objetivo: descubrir un buen presupuesto de tokens por chunk semanal
(aproximación: 1 token ≈ 4 caracteres) mirando la distribución real de los datos.

Uso:
    python3 -m dataanalysis.weekly_token_stats
    # o
    python3 dataanalysis/weekly_token_stats.py
"""

import os
import sys

# Permite ejecutar el script directamente (añade la raíz del proyecto al path)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sqlalchemy import create_engine, text

from src import settings


# Una semana empieza el lunes (DATE_TRUNC('week', ...) en Postgres).
# approx_tokens = total de caracteres del contenido en la semana / 4.
QUERY = text("""
    SELECT
        dm.channel_id,
        DATE_TRUNC('week', dm.message_create_at)                                  AS start_time,
        DATE_TRUNC('week', dm.message_create_at) + INTERVAL '7 days'
            - INTERVAL '1 second'                                                  AS end_time,
        COUNT(dm.id)                                                               AS num_messages,
        CEIL(SUM(LENGTH(COALESCE(dm.content, ''))) / 4.0)::int                     AS approx_tokens
    FROM discord_messages dm
    GROUP BY dm.channel_id, start_time
    ORDER BY dm.channel_id, start_time
""")


PERCENTILES = [0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]


def main():
    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING)

    print("[stats] Consultando mensajes agrupados por canal y semana...")
    df = pd.read_sql(QUERY, engine)

    if df.empty:
        print("[stats] No hay datos.")
        return

    print(f"[stats] Filas (canal-semana): {len(df)} | canales distintos: {df['channel_id'].nunique()}")
    print(f"[stats] Rango de fechas: {df['start_time'].min()} → {df['end_time'].max()}\n")

    summary = df[["num_messages", "approx_tokens"]].describe(percentiles=PERCENTILES)

    # describe() ya incluye mean, min, max y los percentiles pedidos.
    pd.set_option("display.float_format", lambda v: f"{v:,.1f}")
    print("=== Resumen por (canal, semana) ===")
    print(summary)

    # print("\n=== Vista previa de filas ===")
    # print(df.head(10).to_string(index=False))



if __name__ == "__main__":
    main()


"""
python3 -m dataanalysis.weekly_token_stats


"""