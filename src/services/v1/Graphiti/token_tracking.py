"""
Rastreo de tokens (LLM + embedding) POR RESUMEN para la ingesta en Graphiti.

Problema que resuelve
---------------------
- Graphiti trae un TokenUsageTracker, pero OpenAIGenericClient (vLLM) NO registra
  el `usage` que devuelve el endpoint, así que ese contador queda en cero.
- Ningún embedder de Graphiti cuenta tokens.
- La ingesta corre con conf.CONCURRENCY workers en paralelo sobre un MISMO
  llm_client/embedder, por lo que un contador global mezclaría los tokens de
  episodios concurrentes y no podríamos atribuirlos a un summary_id concreto.

Solución
--------
Un acumulador POR EPISODIO guardado en un contextvars.ContextVar. Cada worker abre
`track_episode()` antes de add_episode; todas las llamadas LLM/embedder que Graphiti
lanza por debajo (incluso en sub-tareas de asyncio.gather) heredan el MISMO
acumulador, porque contextvars se copia por-tarea y el objeto es mutable (las
sub-tareas lo mutan, no lo reasignan). Al terminar el episodio se persisten dos
filas (llm + embedding) en la tabla graphiti_token_usage.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import typing
from dataclasses import dataclass

import openai
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel
from sqlalchemy.orm import Session

from graphiti_core.embedder.gemini import GeminiEmbedder
from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, ModelSize
from graphiti_core.llm_client.errors import EmptyResponseError, RateLimitError
from graphiti_core.llm_client.openai_generic_client import (
    DEFAULT_MODEL,
    OpenAIGenericClient,
)
from graphiti_core.prompts.models import Message

from src.discord_models import GraphitiTokenUsage
from src.logging_config import get_logger
from . import conf

logger = get_logger(module_name="token_tracking", DIR="Graphiti")


# ---------------------------------------------------------------------------
# Acumulador por episodio (aislado por tarea con contextvars).
# ---------------------------------------------------------------------------
@dataclass
class EpisodeTokenUsage:
    llm_input: int = 0
    llm_output: int = 0
    embed_input: int = 0
    embed_calls: int = 0


_current_usage: contextvars.ContextVar[EpisodeTokenUsage | None] = contextvars.ContextVar(
    'graphiti_episode_token_usage', default=None
)


@contextlib.contextmanager
def track_episode():
    """Acumula los tokens de todo lo que Graphiti haga dentro del bloque.

    Uso:
        with track_episode() as usage:
            await graphiti.add_episode(...)
        # usage.llm_input / usage.embed_input ... ya están poblados
    """
    usage = EpisodeTokenUsage()
    token = _current_usage.set(usage)
    try:
        yield usage
    finally:
        _current_usage.reset(token)


def persist_episode_usage(
    session: Session,
    summary_id: int,
    channel_id: int,
    usage: EpisodeTokenUsage,
) -> None:
    """Guarda dos filas (llm + embedding) en graphiti_token_usage.

    Defensivo a propósito: un fallo aquí NO debe tumbar la ingesta (el episodio ya
    está en el grafo y marcado in_graphiti). Se loguea y se continúa.
    """
    try:
        session.add_all(
            [
                GraphitiTokenUsage(
                    summary_id=summary_id,
                    channel_id=channel_id,
                    kind='llm',
                    model_name=conf.LLM_MODEL,
                    input_tokens=usage.llm_input,
                    output_tokens=usage.llm_output,
                    embed_calls=None,
                ),
                GraphitiTokenUsage(
                    summary_id=summary_id,
                    channel_id=channel_id,
                    kind='embedding',
                    model_name=conf.EMBED_MODEL,
                    input_tokens=usage.embed_input,
                    output_tokens=0,
                    embed_calls=usage.embed_calls,
                ),
            ]
        )
        session.commit()
        logger.info(
            'tokens summary_id=%s | llm(in=%d out=%d) | embed(in~%d, %d textos)',
            summary_id,
            usage.llm_input,
            usage.llm_output,
            usage.embed_input,
            usage.embed_calls,
        )
    except Exception:
        session.rollback()
        logger.exception('No se pudieron guardar los tokens de summary_id=%s', summary_id)


# ---------------------------------------------------------------------------
# Wrapper del LLM: captura el `usage` real que devuelve vLLM.
# ---------------------------------------------------------------------------
class TokenTrackingOpenAIGenericClient(OpenAIGenericClient):
    """OpenAIGenericClient que suma el `usage` real de vLLM al acumulador por episodio.

    Reimplementa _generate_response (idéntico al de la clase base) añadiendo la
    captura de response.usage, porque la versión original lo descarta.
    """

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, typing.Any]:
        openai_messages: list[ChatCompletionMessageParam] = []
        for m in messages:
            m.content = self._clean_input(m.content)
            if m.role == 'user':
                openai_messages.append({'role': 'user', 'content': m.content})
            elif m.role == 'system':
                openai_messages.append({'role': 'system', 'content': m.content})
        try:
            response = await self.client.chat.completions.create(
                model=self.model or DEFAULT_MODEL,
                messages=openai_messages,
                temperature=self.temperature,
                max_tokens=max_tokens,
                response_format=self._build_response_format(response_model),  # type: ignore[arg-type]
            )

            # --- captura del usage real de vLLM ---
            api_usage = getattr(response, 'usage', None)
            if api_usage is not None:
                inp = getattr(api_usage, 'prompt_tokens', 0) or 0
                out = getattr(api_usage, 'completion_tokens', 0) or 0
                # Mantén vivo también el tracker global de Graphiti (print_summary()).
                self.token_tracker.record(None, inp, out)
                acc = _current_usage.get()
                if acc is not None:
                    acc.llm_input += inp
                    acc.llm_output += out

            result = response.choices[0].message.content or ''
            if not result:
                raise EmptyResponseError('LLM returned an empty response')
            return json.loads(self._strip_code_fences(result))
        except openai.RateLimitError as e:
            raise RateLimitError from e
        except Exception as e:
            logger.error('Error generando respuesta del LLM: %s', e)
            raise


# ---------------------------------------------------------------------------
# Wrapper del embedder: aproxima los tokens del texto enviado a embeber.
# ---------------------------------------------------------------------------
class TokenCountingGeminiEmbedder(GeminiEmbedder):
    """GeminiEmbedder que aproxima los tokens del texto enviado a embeber.

    Usa tiktoken (cl100k_base) si está instalado; si no, cae a la heurística
    chars/4. Para Gemini es una APROXIMACIÓN (~10-20% de error frente al
    tokenizador real), suficiente para estimar coste y dimensionar.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            import tiktoken

            self._enc = tiktoken.get_encoding('cl100k_base')
        except Exception:
            self._enc = None
            logger.warning(
                'tiktoken no disponible; usando heurística chars/4 para tokens de '
                'embedding. Instala tiktoken para una aproximación mejor.'
            )

    def _count(self, text: str) -> int:
        if not text:
            return 0
        if self._enc is not None:
            return len(self._enc.encode(text))
        return max(1, len(text) // 4)

    async def create(self, input_data):
        acc = _current_usage.get()
        if acc is not None and isinstance(input_data, str):
            acc.embed_input += self._count(input_data)
            acc.embed_calls += 1
        return await super().create(input_data)

    async def create_batch(self, input_data_list: list[str]):
        acc = _current_usage.get()
        if acc is not None:
            for t in input_data_list:
                if isinstance(t, str):
                    acc.embed_input += self._count(t)
            acc.embed_calls += len(input_data_list)
        return await super().create_batch(input_data_list)
