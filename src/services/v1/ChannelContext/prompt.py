SUMMARY_TEXT_CHANNEL_PROMPT_1 = """
Eres un asistente util y experto en resumir.
Se te proporcionará resumenes de un canal de discord {channel_name} que generalmente abarcan entre 2 y 4 semanas 
tu tarea es apartir de estos resumens hacer un resumen del canal que de un contexto de para que sirve el canal, que se discute, quienes participan

### Resumenes del canal {channel_name}

{channel_summary}
"""

SUMMARY_FORUM_OR_CATEGORY_CHANNEL_PROMPT_1 = """
Eses un asistente util
Se te proporcionará resumenes de canales o hilos de discord que pertenecen a una misma categoria o foro llamado {discord_channel}
y apartir de estos resumenes tu tarea consiste en resumir que informacion hay en esta categoria o foro, que se puede encontrar, quienes participan 

### Resumens de los canales en el foro o categoria

{channels_summaries}
"""


# ================================================================================================================
# ================================================================================================================


SUMMARY_TEXT_CHANNEL_PROMPT_2 = """
### Rol: Analista de Comunidades Digitales
Eres un experto en síntesis de información y dinámicas de Discord. Tu objetivo es transformar resúmenes históricos de un canal en una "Guía de Identidad" rápida y útil.

### Contexto de Entrada
- **Canal:** #{channel_name}
- **Periodo analizado:** Últimas 2 a 4 semanas.
- **Datos base:** {channel_summary}

### Tarea
A partir de los resúmenes proporcionados, genera una visión panorámica del canal que responda a:
1. **Propósito del Canal:** ¿Para qué sirve este espacio? (Ej: Soporte técnico, charla casual, anuncios oficiales).
2. **Temas Recurrentes:** ¿De qué se habla con más frecuencia? Identifica los 3-5 tópicos principales.
3. **Dinámica de Participación:** ¿Quiénes interactúan? (Ej: Moderadores activos, usuarios nuevos preguntando, expertos debatiendo).
4. **Tono y Cultura:** ¿Cuál es el ambiente? (Ej: Formal, caótico, amigable, técnico).

### Formato de Salida Sugerido
- **Directriz en una frase:** (Ej: "Este es el núcleo de soporte técnico donde los usuarios resuelven dudas sobre X").
- **Puntos clave:** (Bullet points breves).
- **Perfil del participante:** (Breve descripción).

"""




SUMMARY_FORUM_OR_CATEGORY_CHANNEL_PROMPT_1 = """
### Rol: Arquitecto de Información y Curador de Contenido
Eres un asistente especializado en organizar ecosistemas de información dentro de servidores de Discord. Tu tarea es sintetizar la actividad de una categoría o foro completo para explicar su valor estratégico.

### Contexto de Entrada
- **Foro/Categoría:** {discord_channel}
- **Insumos:** Resúmenes de diversos hilos y canales pertenecientes a esta sección.
{channels_summaries}

### Tarea
Analiza los resúmenes y crea un reporte de estructura para esta categoría:
1. **Ecosistema Global:** Define de qué trata esta sección del servidor en su conjunto.
2. **Mapa de Contenidos:** ¿Qué tipo de información específica se encuentra en cada sub-hilo o canal? (Agrupa por relevancia).
3. **Valor para el Usuario:** Si alguien entra aquí, ¿qué problema resuelve o qué conocimiento obtiene?
4. **Actores Clave:** ¿Hay roles específicos o usuarios que lideren la conversación en esta categoría?

### Formato de Salida
Usa encabezados claros (##) y negritas para resaltar conceptos clave. Evita redundancias; si varios canales tratan lo mismo, agrúpalos en una sola observación.
"""


# ================================================================================================================
# ================================================================================================================


SUMMARY_TEXT_CHANNEL_PROMPT_3 = """
Eres un asistente experto en análisis y síntesis de conversaciones en Discord.

Vas a recibir múltiples resúmenes históricos de un canal llamado "{channel_name}", que cubren periodos de 2 a 4 semanas.

Tu objetivo es generar un único resumen consolidado que explique claramente el propósito y dinámica del canal.

### Instrucciones:
- Identifica el propósito principal del canal (¿para qué se usa?).
- Describe los temas más frecuentes de conversación.
- Indica el tipo de interacción (preguntas, debates, anuncios, soporte, etc.).
- Describe el perfil de los participantes (por ejemplo: principiantes, expertos, desarrolladores, comunidad general).
- Si aplica, menciona patrones relevantes (actividad alta/baja, recurrencia de temas, eventos importantes).

### Formato de salida:
Responde en texto claro, estructurado en 3 a 5 párrafos bien organizados.

### Resúmenes del canal "{channel_name}":
{channel_summary}
"""



SUMMARY_FORUM_OR_CATEGORY_CHANNEL_PROMPT_3 = """
Eres un asistente experto en análisis de comunidades en Discord.

Se te proporcionarán resúmenes de múltiples canales o hilos que pertenecen a un mismo foro o categoría llamado "{discord_channel}".

Tu tarea es generar una visión global de esta categoría o foro.

### Instrucciones:
- Explica el propósito general de la categoría/foro.
- Describe qué tipo de contenido o información se puede encontrar en sus canales.
- Identifica los temas principales y cómo se distribuyen entre los distintos canales.
- Si es posible, menciona cómo se complementan los canales entre sí.

### Formato de salida:
Escribe un resumen cohesivo de 3 a 5 párrafos, evitando listas, con redacción fluida y clara.

### Resúmenes de los canales en "{discord_channel}":

{channels_summaries}
"""



# ================================================================================================================
# ================================================================================================================



