"""Hiperparámetros de la rutina de chunkenización cronológica de Discord."""

# Aproximación de tokens: 1 token ≈ CHARS_PER_TOKEN caracteres.
CHARS_PER_TOKEN = 4

# Piso (en tokens). Si el último chunk de un canal está por debajo de T_MIN se
# considera "vivo": al llegar mensajes nuevos se fusionan en él y su resumen se
# invalida (summary = None) para volver a generarlo.
T_MIN = 300

# Techo (en tokens). Ningún chunk debe superar T_MAX. Al empaquetar, si añadir un
# mensaje excediera este valor, se corta el chunk (puede partir una semana muy
# activa en sub-chunks).
T_MAX = 6000

# Tope temporal (en semanas). Un chunk "vivo" que abarque ~W_MAX_WEEKS semanas se
# congela aunque no alcance T_MIN, para no dejar resúmenes pendientes
# indefinidamente en canales de muy bajo tráfico.
W_MAX_WEEKS = 3

# Tipos de canal que no contienen mensajes propios (se ignoran al chunkear).
IGNORED_CHANNEL_TYPES = {"forum", "category"}

# Canales raíz para el modo recursivo (procesa el canal y todos sus hilos hijos).
ROOT_IDS = [1309953285582491649, 1311706520467144808]
