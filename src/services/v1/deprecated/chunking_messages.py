
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.engine import Engine
import pandas as pd
from src import discord_models as models
from datetime import datetime
from typing import List, TypedDict




class SummaryDict(TypedDict):
    summary_from : datetime
    summary_end : datetime
    messages_count : int



def chunking_messages_by_channel(engine: Engine, session: Session, channel_id: int, min_msg: int = 50) -> List[SummaryDict]:
    """
    Funcion para chunkenizar los mensajes en intervalos de tiempo De tal forma que se tienda a haber mas de 50 mensajes por chunk
    
    """

    channel = session.query(models.DiscordChannel).filter_by(id=channel_id).first()
    print(f"[chunking] Canal: '{channel.name}' (id={channel_id}, tipo={channel.channel_type})")
    if channel.channel_type in {"forum", "category"}:
        print(f"[chunking] ↳ Ignorado: es foro o categoría")
        return



    record = session.query(models.DiscordChannelChronologicalSummary).filter(
        models.DiscordChannelChronologicalSummary.channel_id == channel_id
    ).order_by(models.DiscordChannelChronologicalSummary.start_time.desc()).first()


    if record is None:
        print(f"[chunking] No hay registros previos en DiscordChannelChronologicalSummary → chunkenizando desde el inicio")
        last_saved_message = None
    else:
        print(f"[chunking] Registro previo encontrado → último chunk desde {record.start_time} hasta {record.end_time}. Chunkenizando mensajes nuevos")
        last_saved_message = record.end_time

    print(f"[chunking] Consultando mensajes agrupados por semana...")
    query = text("""
        SELECT
            COUNT(dm.id) as total_messages,
            DATE_TRUNC('week', dm.message_create_at) as week_start_by,
            DATE_TRUNC('week', dm.message_create_at) + INTERVAL '7 days' - INTERVAL '1 second' as week_end_by
        FROM discord_messages dm
        WHERE
            dm.channel_id = :channel_id AND
            (
                :last_saved_message IS NULL OR
                dm.message_create_at > :last_saved_message
            )
        GROUP BY week_start_by
        ORDER BY week_start_by
    """)
    df = pd.read_sql(query, engine, params={"channel_id": channel_id, "last_saved_message":last_saved_message})

    if df.empty:
        print(f"[chunking] ↳ Sin mensajes nuevos para chunkenizar")
        return

    total_msgs = int(df["total_messages"].sum())
    print(f"[chunking] ↳ {len(df)} semanas encontradas, {total_msgs} mensajes en total")

    summary_list = []
    x = 0
    # Inicializamos con los datos de la primera fila
    current_count = df.loc[0, "total_messages"]

    # Un solo puntero 'y' para recorrer las semanas
    for y in range(len(df)):
        # Si ya alcanzamos el mínimo y no es la última fila, cerramos este chunk
        # (Excepto si es el último, que se maneja fuera del loop o al final)
        if current_count >= min_msg and y < len(df) - 1:
            summary_list.append({
                'summary_from': df.loc[x, "week_start_by"],
                'summary_end': df.loc[y, "week_end_by"],
                'messages_count': int(current_count)
            })
            print(f"[chunking]   chunk #{len(summary_list)}: semanas {x}→{y} | {current_count} mensajes")
            x = y + 1
            if x < len(df):
                current_count = df.loc[x, "total_messages"]
        else:
            # Si no hemos llegado al mínimo, sumamos la siguiente semana (si existe)
            if y + 1 < len(df):
                current_count += df.loc[y + 1, "total_messages"]

    # Agregar el último remanente
    if x < len(df):
        summary_list.append({
            'summary_from': df.loc[x, "week_start_by"],
            'summary_end': df.loc[len(df)-1, "week_end_by"],
            'messages_count': int(current_count)
        })
        print(f"[chunking]   chunk #{len(summary_list)} (remanente): semanas {x}→{len(df)-1} | {current_count} mensajes")

    # Lógica de fusión: Si el último chunk es muy pequeño, unirlo al penúltimo
    if len(summary_list) > 1 and summary_list[-1]['messages_count'] < min_msg:
        last = summary_list.pop()
        summary_list[-1]['summary_end'] = last['summary_end']
        summary_list[-1]['messages_count'] += last['messages_count']
        print(f"[chunking] Último chunk pequeño (<{min_msg} msgs) fusionado con el penúltimo → ahora {summary_list[-1]['messages_count']} mensajes")


    print(f"[chunking] Ajustando timestamps al primer y último mensaje real...")
    first_dict = summary_list[0]
    first_message_in_df = session.query(models.DiscordMessage).filter(
        models.DiscordMessage.channel_id == channel_id,
        models.DiscordMessage.message_create_at >= first_dict['summary_from'],
        models.DiscordMessage.message_create_at <= first_dict['summary_end']
    ).order_by(models.DiscordMessage.message_create_at).first()


    last_dict = summary_list[-1]
    last_message_in_df = session.query(models.DiscordMessage).filter(
        models.DiscordMessage.channel_id == channel_id,
        models.DiscordMessage.message_create_at >= last_dict['summary_from'],
        models.DiscordMessage.message_create_at <= last_dict['summary_end']
    ).order_by(models.DiscordMessage.message_create_at.desc()).first()

    summary_list[0]['summary_from'] = first_message_in_df.message_create_at
    summary_list[-1]['summary_end'] = last_message_in_df.message_create_at

    print(f"[chunking] ✓ Canal '{channel.name}': {len(summary_list)} chunks generados")

    return summary_list








def save_chunked_messages_by_channel(session : Session, channel_id : int, summary_list : List[SummaryDict] , min_msg : int = 50):
    print(f"[save] Guardando chunks del canal {channel_id} ({len(summary_list)} chunks nuevos)")
    summary_records = session.query(models.DiscordChannelChronologicalSummary).filter(
        models.DiscordChannelChronologicalSummary.channel_id == channel_id
    ).order_by(models.DiscordChannelChronologicalSummary.start_time).all()

    print(f"[save] Registros existentes en DB: {len(summary_records)}")

    # Caso 1
    if not summary_records:
        print("[save] Caso 1: sin registros previos → insertando todos los chunks")
        for summ_dict in summary_list:
            record = models.DiscordChannelChronologicalSummary(
                channel_id=channel_id,
                start_time=summ_dict.get("summary_from"),
                end_time=summ_dict.get("summary_end"),
                number_messages=summ_dict.get("messages_count"),
                summary=None,
                #status=None,
            )
            session.add(record)

        session.commit()
        print(f"[save] ✓ {len(summary_list)} chunks insertados")
        return

    last_summary_record = summary_records[-1]
    first_summary_record = summary_records[0]

    last_summary_list = summary_list[-1]
    first_summary_list = summary_list[0]



    # Caso 2
    if (last_summary_record.number_messages >= min_msg) and (last_summary_list.get("messages_count") >= min_msg):
        print(f"[save] Caso 2: último registro DB tiene {last_summary_record.number_messages} msgs (≥{min_msg}) y primer chunk nuevo tiene {last_summary_list.get('messages_count')} msgs → insertando todos")
        for summ_dict in summary_list:
            record = models.DiscordChannelChronologicalSummary(
                channel_id=channel_id,
                start_time=summ_dict.get("summary_from"),
                end_time=summ_dict.get("summary_end"),
                number_messages=summ_dict.get("messages_count"),
                summary=None,
                #status=None,
            )
            session.add(record)

        session.commit()
        print(f"[save] ✓ {len(summary_list)} chunks insertados")
        return


    # Caso 3
    if (len(summary_list) == 1):
        print(f"[save] Caso 3: solo 1 chunk nuevo → fusionando con último registro DB (antes: {last_summary_record.number_messages} msgs, después: {first_summary_list.get('messages_count') + last_summary_record.number_messages} msgs)")
        last_summary_record.end_time = first_summary_list.get("summary_end")
        last_summary_record.number_messages = first_summary_list.get("messages_count") + last_summary_record.number_messages
        last_summary_record.summary = None
        #last_summary_record.status = None
        session.add(last_summary_record)
        session.commit()
        print(f"[save] ✓ Registro actualizado")
        return


    # Caso 4
    if (summary_list > 1) and (len(summary_records) == 1) and (first_summary_record.number_messages < min_msg):
        print(f"[save] Caso 4: registro DB único con {first_summary_record.number_messages} msgs (<{min_msg}) → fusionando con primer chunk nuevo y añadiendo el resto")
        first_summary_record.end_time = first_summary_list.get("summary_end")
        first_summary_record.number_messages = first_summary_list.get("messages_count") + first_summary_record.number_messages
        first_summary_record.summary = None
        #first_summary_record.status = None
        session.add(first_summary_record)
        for i in range(1, len(summary_list)):
            summ_dict = summary_list[i]
            record = models.DiscordChannelChronologicalSummary(
                channel_id=channel_id,
                start_time=summ_dict.get("summary_from"),
                end_time=summ_dict.get("summary_end"),
                number_messages=summ_dict.get("messages_count"),
                summary=None,
            )
            session.add(record)
            
        session.commit()
        print(f"[save] ✓ Registro fusionado + {len(summary_list) - 1} chunks nuevos insertados")
        return

    raise ValueError("Caso Desconocido")

    
    


def chunking_recursively_by_channel_id(engine: Engine, session: Session, channel_id: int, min_msg: int = 50):
    print(f"\n[recurse] ── Procesando canal {channel_id} ──")
    summary_list = chunking_messages_by_channel(engine=engine, session=session, channel_id=channel_id, min_msg=min_msg)
    if summary_list is None:
        print(f"[recurse] Sin chunks para guardar en canal {channel_id}")
    else:
        print(f"[recurse] {len(summary_list)} chunks generados → guardando...")
        save_chunked_messages_by_channel(session=session, channel_id=channel_id, summary_list=summary_list)

    channels_records = session.query(models.DiscordChannel).filter_by(parent_channel_id=channel_id).all()
    print(f"[recurse] Canal {channel_id} tiene {len(channels_records)} hijos")
    if not channels_records:
        return

    for obj in channels_records:
        chunking_recursively_by_channel_id(engine=engine, session=session, channel_id=obj.id, min_msg=min_msg)
    


if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src import settings

    engine = create_engine(settings.DB_DISCORD_CONN_STRING)
    MySession = sessionmaker(bind=engine)
    session = MySession()


    # summary_list = chunking_messages_by_channel(engine=engine, session=session, channel_id=1399093133056278549)
    # for s in summary_list:
    #     print(s)
    # print("\n\n")

    # save_chunked_messages_by_channel(session=session, channel_id=1399093133056278549, summary_list=summary_list)


    root_id = 1309953285582491649
    #root_id = 1311706520467144808
    chunking_recursively_by_channel_id(engine=engine, session=session, channel_id=root_id)





"""
python3 -m src.services.v1.DiscordGraph.chunking_messages


"""