"""
Rutina de chunkenización cronológica de mensajes de Discord (v1 · DiscordSumaries).

Refactor de services/v1/deprecated/chunking_messages.py.

En vez del umbral fijo de 50 mensajes, agrupa los mensajes por un presupuesto de
tokens (aprox. 1 token ≈ conf.CHARS_PER_TOKEN caracteres) con tres parámetros
(ver conf.py):

  - T_MIN        piso. El último chunk por debajo de este tamaño se considera
                 "vivo": al llegar mensajes nuevos se fusionan en él y su resumen
                 se invalida (summary = None).
  - T_MAX        techo. Ningún chunk lo supera; si se excede, se parte (puede
                 dividir una semana muy activa en sub-chunks).
  - W_MAX_WEEKS  tope temporal. Un chunk vivo que abarque ~W_MAX_WEEKS semanas se
                 congela aunque no alcance T_MIN (frescura en canales lentos).

Los cortes se prefieren en frontera de semana (lunes, igual que DATE_TRUNC('week')
en Postgres), salvo el corte duro por T_MAX.

Cada ejecución sobre un canal:
  - Primera vez: chunkeniza todo el histórico del canal.
  - Siguientes:  solo procesa mensajes nuevos. Si el último chunk seguía "vivo",
                 lo reabre, fusiona lo nuevo y pone summary = None para re-resumir.

Este módulo NO genera resúmenes; solo crea/actualiza los registros de chunk
(DiscordChannelChronologicalSummary), dejando summary = None donde corresponda.
La madurez del último chunk se recalcula leyendo los mensajes en cada corrida, así
que no requiere columnas extra ni estado persistido.

Uso:
    python3 -m src.services.v1.DiscordSumaries.chunking
"""

from datetime import datetime, timedelta
from typing import List, Optional, Sequence, Tuple, TypedDict

from sqlalchemy import func
from sqlalchemy.orm import Session

from src import discord_models as models
from src.logging_config import get_logger
from src.services.v1.DiscordSumaries import conf

logger = get_logger(module_name="chunking", DIR="DiscordSumaries", to_db=True)


class ChunkDict(TypedDict):
    start_time: datetime
    end_time: datetime
    number_messages: int
    approx_tokens: int


# ──────────────────────────── helpers ────────────────────────────

def _week_floor(dt: datetime) -> datetime:
    """Lunes 00:00 de la semana de dt (equivale a DATE_TRUNC('week') en Postgres)."""
    monday = dt - timedelta(days=dt.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def _tokens(char_total: int) -> float:
    """Tokens aproximados a partir del total de caracteres."""
    return char_total / conf.CHARS_PER_TOKEN


# ──────────────────────────── packing ────────────────────────────

def _pack_messages(rows: Sequence[Tuple[datetime, int]]) -> List[ChunkDict]:
    """
    Empaqueta mensajes (en orden cronológico) en chunks según el presupuesto de
    tokens. `rows` es una secuencia de (message_create_at, char_len).

    Regla de corte:
      - en frontera de semana, si el chunk acumulado ya está "maduro"
        (>= T_MIN tokens, o abarca >= W_MAX_WEEKS semanas);
      - o corte duro si añadir el mensaje superara T_MAX tokens.
    El último chunk (remanente) puede quedar inmaduro: es el chunk "vivo".
    """
    chunks: List[ChunkDict] = []
    cur: Optional[dict] = None

    def close(c: dict) -> ChunkDict:
        return {
            "start_time": c["start"],
            "end_time": c["end"],
            "number_messages": c["n"],
            "approx_tokens": round(_tokens(c["chars"])),
        }

    for create_at, char_len in rows:
        msg_tokens = _tokens(char_len)

        if cur is not None:
            crossing_week = _week_floor(create_at) != cur["week"]
            span_days = (_week_floor(cur["end"]) - cur["start_week"]).days
            mature = _tokens(cur["chars"]) >= conf.T_MIN or span_days >= conf.W_MAX_WEEKS * 7
            would_exceed = _tokens(cur["chars"]) + msg_tokens > conf.T_MAX

            if (crossing_week and mature) or would_exceed:
                chunks.append(close(cur))
                cur = None

        if cur is None:
            week = _week_floor(create_at)
            cur = {
                "start": create_at,
                "start_week": week,
                "end": create_at,
                "week": week,
                "n": 0,
                "chars": 0,
            }

        cur["end"] = create_at
        cur["week"] = _week_floor(create_at)
        cur["n"] += 1
        cur["chars"] += char_len

    if cur is not None:
        chunks.append(close(cur))

    return chunks


# ──────────────────────────── queries ────────────────────────────

def _fetch_message_rows(
    session: Session, channel_id: int, after: Optional[datetime], inclusive: bool
) -> List[Tuple[datetime, int]]:
    """(message_create_at, char_len) de los mensajes del canal, ordenados ascendente."""
    q = session.query(
        models.DiscordMessage.message_create_at,
        func.length(func.coalesce(models.DiscordMessage.content, "")),
    ).filter(models.DiscordMessage.channel_id == channel_id)

    if after is not None:
        if inclusive:
            q = q.filter(models.DiscordMessage.message_create_at >= after)
        else:
            q = q.filter(models.DiscordMessage.message_create_at > after)

    return q.order_by(models.DiscordMessage.message_create_at.asc()).all()


def _count_messages_after(session: Session, channel_id: int, after: datetime) -> int:
    return (
        session.query(func.count(models.DiscordMessage.id))
        .filter(
            models.DiscordMessage.channel_id == channel_id,
            models.DiscordMessage.message_create_at > after,
        )
        .scalar()
        or 0
    )


def _chunk_tokens(session: Session, channel_id: int, start: datetime, end: datetime) -> float:
    """Tokens aproximados del contenido de un rango [start, end]."""
    chars = (
        session.query(
            func.coalesce(func.sum(func.length(func.coalesce(models.DiscordMessage.content, ""))), 0)
        )
        .filter(
            models.DiscordMessage.channel_id == channel_id,
            models.DiscordMessage.message_create_at >= start,
            models.DiscordMessage.message_create_at <= end,
        )
        .scalar()
        or 0
    )
    return _tokens(chars)


def is_chunk_mature(session: Session, record: models.DiscordChannelChronologicalSummary) -> bool:
    """
    True si el chunk ya no volverá a re-chunkenizarse/re-resumirse (espejo exacto de
    la decisión de rechunk_channel):

      - si record.status == True → ya declarado maduro (fuente de verdad);
      - si existe un chunk posterior del mismo canal → congelado para siempre;
      - si es el último chunk del canal → maduro solo si ya está "maduro de
        contenido": >= T_MIN tokens, o abarca >= W_MAX_WEEKS semanas.
    """
    if record.status is True:
        return True

    has_successor = (
        session.query(models.DiscordChannelChronologicalSummary.id)
        .filter(
            models.DiscordChannelChronologicalSummary.channel_id == record.channel_id,
            models.DiscordChannelChronologicalSummary.start_time > record.start_time,
        )
        .first()
        is not None
    )
    if has_successor:
        return True

    tokens = _chunk_tokens(session, record.channel_id, record.start_time, record.end_time)
    span_days = (_week_floor(record.end_time) - _week_floor(record.start_time)).days
    return tokens >= conf.T_MIN or span_days >= conf.W_MAX_WEEKS * 7


# ──────────────────────────── persistence ────────────────────────────

def _persist(
    session: Session,
    channel_id: int,
    chunks: List[ChunkDict],
    reopen_record: Optional[models.DiscordChannelChronologicalSummary],
) -> None:
    if not chunks:
        return

    if reopen_record is not None:
        first = chunks[0]
        changed = (
            reopen_record.end_time != first["end_time"]
            or reopen_record.number_messages != first["number_messages"]
        )
        if changed:
            reopen_record.end_time = first["end_time"]
            reopen_record.number_messages = first["number_messages"]
            reopen_record.summary = None  # invalidar: el resumen debe rehacerse
            reopen_record.status = False  # sigue siendo "vivo" → re-evaluable por seed_mature_status
            reopen_record.alerts_done = False  # contenido cambió → re-extraer alertas
            session.add(reopen_record)

            # El contenido del chunk cambió → lo ya ingerido downstream quedó obsoleto.
            # Reseteamos los estados de discord_summary_state a NULL (= pendiente de
            # re-procesar), análogo a summary=None / alerts_done=False.
            state = (
                session.query(models.DiscordSummaryStatus)
                .filter(models.DiscordSummaryStatus.summary_id == reopen_record.id)
                .first()
            )
            if state is not None:
                state.lightrag_status = None
                state.naive_rag_status = None
                state.graphiti_status = None
                session.add(state)
            else:
                # Defensivo: si por algún motivo no existe la fila de estado, la creamos.
                session.add(models.DiscordSummaryStatus(summary_id=reopen_record.id))

            # Defensivo: aunque LightRAG solo debería ingerir chunks maduros, si por
            # algún motivo este chunk vivo ya tenía docs en LightRAG, su contenido
            # cambió → marcarlos para purgar y re-ingerir.
            session.query(models.LightRagDocs).filter_by(
                summary_id=reopen_record.id
            ).update(
                {models.LightRagDocs.pending_deletion: True},
                synchronize_session=False,
            )

            logger.info(
                "[%s] Chunk vivo reabierto (id=%s) → %s→%s, %s msgs (~%s tokens). "
                "summary=None, estados downstream → NULL",
                channel_id, reopen_record.id, first["start_time"], first["end_time"],
                first["number_messages"], first["approx_tokens"],
            )
        else:
            logger.info(
                "[%s] Último chunk (id=%s) sin cambios reales; se conserva su resumen",
                channel_id, reopen_record.id,
            )
        rest = chunks[1:]
    else:
        rest = chunks

    for c in rest:
        summary = models.DiscordChannelChronologicalSummary(
            channel_id=channel_id,
            start_time=c["start_time"],
            end_time=c["end_time"],
            number_messages=c["number_messages"],
            summary=None,
            status=False,
        )
        session.add(summary)
        # Necesitamos el id autoincremental para enlazar el estado downstream.
        session.flush()
        # Estado downstream del chunk recién creado: aún no ingerido en ningún
        # backend → todos los estados arrancan en NULL (pendiente).
        session.add(models.DiscordSummaryStatus(summary_id=summary.id))
        logger.debug(
            "[%s] Nuevo chunk: %s→%s, %s msgs (~%s tokens), estado creado (summary_id=%s)",
            channel_id, c["start_time"], c["end_time"], c["number_messages"],
            c["approx_tokens"], summary.id,
        )

    session.commit()
    logger.info(
        "[%s] Persistencia OK: %s chunk(s) nuevo(s)%s",
        channel_id, len(rest), " + 1 reabierto" if reopen_record is not None else "",
    )


# ──────────────────────────── entrypoints ────────────────────────────

def rechunk_channel(session: Session, channel_id: int) -> None:
    """Chunkeniza (o re-chunkeniza incrementalmente) un único canal."""
    channel = session.query(models.DiscordChannel).filter_by(id=channel_id).first()
    if channel is None:
        logger.warning("[%s] Canal no encontrado", channel_id)
        return

    logger.info("[%s] Canal '%s' (tipo=%s)", channel_id, channel.name, channel.channel_type)
    if channel.channel_type in conf.IGNORED_CHANNEL_TYPES:
        logger.info("[%s] Ignorado: tipo '%s' no contiene mensajes propios", channel_id, channel.channel_type)
        return

    last = (
        session.query(models.DiscordChannelChronologicalSummary)
        .filter(models.DiscordChannelChronologicalSummary.channel_id == channel_id)
        .order_by(models.DiscordChannelChronologicalSummary.start_time.desc())
        .first()
    )

    # Primera vez: chunkenizar todo el histórico.
    if last is None:
        logger.info("[%s] Sin chunks previos → chunkenizando todo el histórico", channel_id)
        rows = _fetch_message_rows(session, channel_id, after=None, inclusive=False)
        if not rows:
            logger.info("[%s] Canal sin mensajes; nada que hacer", channel_id)
            return
        chunks = _pack_messages(rows)
        _persist(session, channel_id, chunks, reopen_record=None)
        return

    # Ejecuciones incrementales.
    new_count = _count_messages_after(session, channel_id, last.end_time)
    if new_count == 0:
        logger.info("[%s] Sin mensajes nuevos desde %s; nada que hacer", channel_id, last.end_time)
        return

    last_tokens = _chunk_tokens(session, channel_id, last.start_time, last.end_time)
    span_days = (_week_floor(last.end_time) - _week_floor(last.start_time)).days
    # status=True actúa como override autoritativo: el chunk queda congelado aunque
    # por contenido aún parezca "vivo" (p.ej. tras un force_merge manual).
    is_live = (
        last.status is not True
        and last_tokens < conf.T_MIN
        and span_days < conf.W_MAX_WEEKS * 7
    )

    logger.info(
        "[%s] %s mensaje(s) nuevo(s). Último chunk id=%s: status=%s, ~%s tokens, span=%sd → %s",
        channel_id, new_count, last.id, last.status, round(last_tokens), span_days,
        "VIVO (se reabre y fusiona)" if is_live else "congelado (solo mensajes nuevos)",
    )

    if is_live:
        rows = _fetch_message_rows(session, channel_id, after=last.start_time, inclusive=True)
        chunks = _pack_messages(rows)
        _persist(session, channel_id, chunks, reopen_record=last)
    else:
        rows = _fetch_message_rows(session, channel_id, after=last.end_time, inclusive=False)
        chunks = _pack_messages(rows)
        _persist(session, channel_id, chunks, reopen_record=None)






def rechunk_channel_recursive(session: Session, channel_id: int) -> None:
    """Chunkeniza un canal y, recursivamente, todos sus hilos/canales hijos."""
    rechunk_channel(session, channel_id)

    children = (
        session.query(models.DiscordChannel).filter_by(parent_channel_id=channel_id).all()
    )
    if children:
        logger.info("[%s] %s canal(es) hijo(s) por procesar", channel_id, len(children))
    for child in children:
        rechunk_channel_recursive(session, child.id)





def rechunk_all_available_channels(session: Session):
    # Todos los canales que tienen mensajes (last_messages_at no nulo). NO filtramos
    # por summary IS NULL: eso solo detectaba canales con un chunk pendiente y dejaba
    # fuera a los canales que ya estaban resumidos pero recibieron mensajes nuevos.
    # rechunk_channel es idempotente y retorna barato cuando no hay nada nuevo.
    channel_records = (
        session.query(models.DiscordChannel.id)
        .filter(models.DiscordChannel.last_messages_at.is_not(None))
        .all()
    )

    logger.info("Canales a evaluar: %s", len(channel_records))
    for (channel_id,) in channel_records:
        rechunk_channel(session=session, channel_id=channel_id)





if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src import settings
    from src.logging_config import setup_base_logging

    setup_base_logging()

    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()


    rechunk_all_available_channels(session=session)
    session.close()



"""
python3 -m src.services.v1.DiscordSumaries.chunking



"""