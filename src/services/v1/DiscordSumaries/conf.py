"""Hiperparámetros de la rutina de chunkenización cronológica de Discord."""

# Aproximación de tokens: 1 token ≈ CHARS_PER_TOKEN caracteres.
CHARS_PER_TOKEN = 4

# Piso (en tokens). Si el último chunk de un canal está por debajo de T_MIN se
# considera "vivo": al llegar mensajes nuevos se fusionan en él y su resumen se
# invalida (summary = None) para volver a generarlo.
T_MIN = 10000

# Techo (en tokens). Ningún chunk debe superar T_MAX. Al empaquetar, si añadir un
# mensaje excediera este valor, se corta el chunk (puede partir una semana muy
# activa en sub-chunks).
T_MAX = 200000

# Tope temporal (en semanas). Un chunk "vivo" que abarque ~W_MAX_WEEKS semanas se
# congela aunque no alcance T_MIN, para no dejar resúmenes pendientes
# indefinidamente en canales de muy bajo tráfico.
W_MAX_WEEKS = 4

# Tipos de canal que no contienen mensajes propios (se ignoran al chunkear).
IGNORED_CHANNEL_TYPES = {"forum", "category"}

