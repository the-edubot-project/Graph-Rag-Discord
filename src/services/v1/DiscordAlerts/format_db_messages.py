from sqlalchemy.orm import Session
from src import discord_models as models
from datetime import datetime

import re
from sqlalchemy.orm import Session
from datetime import datetime


from src.logging_config import get_logger
logger = get_logger(module_name="format_db_messages.py", DIR="DiscordSumaries")


def format_db_messageses(session: Session, channel_id: int, summary_from: datetime, summary_end: datetime):
    logger.info("format_db_messageses")
    # 1. Recuperar todos los mensajes del rango de una sola vez
    message_content_records = session.query(models.DiscordMessage).filter(
        models.DiscordMessage.channel_id == channel_id,
        models.DiscordMessage.message_create_at >= summary_from,
        models.DiscordMessage.message_create_at <= summary_end
    ).order_by(models.DiscordMessage.message_create_at.asc()).all()

    if not message_content_records:
        logger.warning(f"No existen mensjaes en {channel_id}, desde {summary_from} hasta {summary_end}")
        return ""

    # 2. Crear un mapa de UserID -> Name y MessageID -> MessageRecord
    # Esto evita consultas repetitivas a la base de datos (N+1)
    user_map = {str(msg.user_id): msg.user_name for msg in message_content_records}
    msg_map = {msg.id: msg for msg in message_content_records}

    # 3. Función para reemplazar menciones <@ID> por @Nombre
    def replace_mentions(text, mapping):
        if not text: return ""
        # Busca el patrón <@números>
        return re.sub(r'<@!?(\d+)>', lambda m: f"@{mapping.get(m.group(1), 'usuario_desconocido')}", text)

    # Plantillas optimizadas
    TEMPLATE_1 = "User: {user_name}  | Date: {date}\nContent: {content}\n\n" # (ID: {user_id})
    TEMPLATE_2 = "User: {user_name}  | Date: {date} | Reply to: {reply_to_name}\nContent: {content}\n\n" # (ID: {user_id})

    final_transcript = []

    for obj in message_content_records:
        try:
            # Limpiar el contenido reemplazando IDs por nombres
            clean_content = replace_mentions(obj.content, user_map)
            date_str = obj.message_create_at.strftime("%d/%m/%Y %H:%M")
            
            # Lógica de respuesta
            if obj.reply_to:
                # Intentamos buscar el nombre en nuestro mapa local primero
                parent_msg = msg_map.get(obj.reply_to)
                if parent_msg:
                    reply_name = parent_msg.user_display_name
                else:
                    # Si la respuesta es a un mensaje fuera de este rango de tiempo,
                    # podrías hacer una consulta rápida o poner "mensaje previo"
                    reply_name = "usuario_en_hilo_anterior"
                
                msg_text = TEMPLATE_2.format(
                    user_name=obj.user_display_name,
                    #user_id=obj.user_id,
                    date=date_str,
                    reply_to_name=reply_name,
                    content=clean_content
                )
            else:
                msg_text = TEMPLATE_1.format(
                    user_name=obj.user_display_name,
                    #user_id=obj.user_id,
                    date=date_str,
                    content=clean_content
                )
            
            final_transcript.append(msg_text)

        except Exception as e:
            logger.error(f"Error procesando mensaje {obj.id}, desde {summary_from} hasta {summary_end} \n: {e}")

    return "".join(final_transcript)



if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src import settings
    from datetime import datetime

    engine = create_engine(settings.DB_DISCORD_CONN_STRING)
    MySession = sessionmaker(bind=engine)
    session = MySession()

    channel_id = 1408492880976416798
    summary_from = "2025-08-22 16:47:51.357"
    summary_end = "2025-09-08 21:35:56.512"


    summary_from = datetime.fromisoformat(summary_from)
    summary_end = datetime.fromisoformat(summary_end)

    txt = format_db_messageses(session=session, channel_id=channel_id, summary_from=summary_from, summary_end=summary_end)

    print(txt)


"""
python3 -m src.services.v1.DiscordSumaries.format_db_messages



"""