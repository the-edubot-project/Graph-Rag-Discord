"""
Helpers para ingerir resúmenes de discord_chronological_summary en Graphiti y
para recuperar información del grafo con filtro temporal.

Cada resumen se inserta como un "episodio" de Graphiti:
  - episode_body  <- summary
  - reference_time <- start_time   (Graphiti lo propaga a valid_at de los hechos)
  - group_id      <- channel_id    (partición del grafo por canal)

Esto es lo que hace que Graphiti sea temporal: los hechos (edges) extraídos
quedan anclados a la ventana temporal del resumen y se pueden filtrar por fecha
en la recuperación (ver search_in_window).
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from graphiti_core.search.search_filters import (
    SearchFilters,
    DateFilter,
    ComparisonOperator,
)

from src.logging_config import get_logger
from src import discord_models as dmodels
from . import conf

logger = get_logger(module_name="graphiti_helper", DIR="Graphiti")


# Namespace estable para derivar UUIDs deterministas de episodio a partir del
# summary_id. Reinsertar el mismo resumen reutiliza el mismo UUID en vez de
# crear un episodio duplicado.
_EPISODE_NS = uuid.uuid5(uuid.NAMESPACE_URL, "discord-chronological-summary")


def _as_utc(dt: datetime) -> datetime:
    """Graphiti compara fechas en Neo4j; conviene que sean tz-aware (UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def mark_ready_for_graphiti(session: Session) -> None:
    """
    Marca como 'ready' (listos para ingerir en Graphiti) los resúmenes que ya
    son inmutables (status == True) y que todavía no tienen graphiti_status.

    Análogo a lightrag_helper.mark_ready_for_lightrag, pero usando la columna
    graphiti_status de DiscordSummaryStatus.
    """
    records = (
        session.query(dmodels.DiscordChannelChronologicalSummary.id)
        .join(
            dmodels.DiscordSummaryStatus,
            dmodels.DiscordSummaryStatus.summary_id
            == dmodels.DiscordChannelChronologicalSummary.id,
        )
        .filter(
            dmodels.DiscordChannelChronologicalSummary.status.is_(True),
            dmodels.DiscordSummaryStatus.graphiti_status.is_(None),
        )
        .all()
    )

    if not records:
        logger.info("No hay resúmenes nuevos que marcar como 'ready' para Graphiti")
        return

    ids = [r.id for r in records]

    status_records = (
        session.query(dmodels.DiscordSummaryStatus)
        .filter(dmodels.DiscordSummaryStatus.summary_id.in_(ids))
        .all()
    )

    for r in status_records:
        r.graphiti_status = "ready"
        session.add(r)

    session.commit()
    logger.info("Marcados %d resúmenes como 'ready' para Graphiti", len(status_records))


async def insert_to_graphiti(
    graphiti: Graphiti,
    session: Session,
    summary_id: int,
    channel_id: int,
    start_time: datetime,
    end_time: datetime,
    summary: str,
) -> None:
    """
    Inserta un resumen como episodio en Graphiti, anclado temporalmente a
    start_time y particionado por canal (group_id).
    """
    if not summary or not summary.strip():
        logger.warning("summary_id=%s tiene summary vacío, saltando", summary_id)
        return

    channel_record = (
        session.query(dmodels.DiscordChannel).filter_by(id=channel_id).first()
    )
    if channel_record is None:
        raise ValueError(f"No se encontró DiscordChannel con id={channel_id}")

    group_id = conf.group_id_for_channel(channel_id)
    ref_time = _as_utc(start_time)
    end_utc = _as_utc(end_time)

    episode_uuid = str(uuid.uuid5(_EPISODE_NS, str(summary_id)))
    name = f"discord-summary-{summary_id}"
    source_description = (
        f"Resumen cronológico de #{channel_record.name} "
        f"({ref_time:%Y-%m-%d %H:%M} a {end_utc:%Y-%m-%d %H:%M} UTC)"
    )

    # Contexto: últimos episodios del mismo canal antes de este resumen. Da
    # continuidad temporal a la extracción (igual que el ejemplo del podcast).
    previous = await graphiti.retrieve_episodes(
        ref_time, last_n=5, group_ids=[group_id]
    )
    previous_uuids = [e.uuid for e in previous]

    logger.info(
        "Ingiriendo summary_id=%s canal=%s (%s)",
        summary_id, channel_record.name, group_id,
    )

    await graphiti.add_episode(
        name=name,
        episode_body=summary,
        source=EpisodeType.text,
        source_description=source_description,
        reference_time=ref_time,
        group_id=group_id,
        uuid=episode_uuid,
        previous_episode_uuids=previous_uuids,
    )

    # add_episode bloquea hasta terminar el procesamiento -> marcamos estado.
    status_record = (
        session.query(dmodels.DiscordSummaryStatus)
        .filter_by(summary_id=summary_id)
        .first()
    )
    if status_record:
        status_record.graphiti_status = "in_graphiti"
        session.add(status_record)
        session.commit()

    logger.info("Ingerido en Graphiti: summary_id=%s episode_uuid=%s", summary_id, episode_uuid)


async def search_in_window(
    graphiti: Graphiti,
    query: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    channel_id: Optional[int] = None,
    num_results: int = 10,
):
    """
    Recupera hechos (edges) del grafo filtrando por la ventana temporal en la
    que el hecho fue válido (valid_at). Ejemplo de "información de hace 4 meses".

      since / until : límites del rango sobre valid_at (tz-aware o naive=UTC).
      channel_id    : si se indica, acota la búsqueda a ese canal (group_id).

    SearchFilters.valid_at es list[list[DateFilter]]: la lista externa es un OR
    de grupos y la interna un AND; aquí usamos un único grupo AND (since..until).
    """
    date_filters: list[DateFilter] = []
    if since is not None:
        date_filters.append(
            DateFilter(
                date=_as_utc(since),
                comparison_operator=ComparisonOperator.greater_than_equal,
            )
        )
    if until is not None:
        date_filters.append(
            DateFilter(
                date=_as_utc(until),
                comparison_operator=ComparisonOperator.less_than_equal,
            )
        )

    search_filter = SearchFilters(valid_at=[date_filters]) if date_filters else SearchFilters()
    group_ids = [conf.group_id_for_channel(channel_id)] if channel_id is not None else None

    return await graphiti.search(
        query,
        group_ids=group_ids,
        num_results=num_results,
        search_filter=search_filter,
    )
