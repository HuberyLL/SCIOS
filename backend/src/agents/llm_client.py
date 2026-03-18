"""Unified LLM client: async OpenAI-compatible calls with structured Pydantic output."""

from __future__ import annotations

import logging
from typing import TypeVar

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.core.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Return a module-level singleton ``AsyncOpenAI`` configured via ``Settings``."""
    global _client
    if _client is None:
        cfg = get_settings()
        _client = AsyncOpenAI(
            base_url=cfg.llm_base_url,
            api_key=cfg.llm_api_key,
        )
    return _client


def _default_model() -> str:
    return get_settings().llm_model


@retry(
    retry=retry_if_exception_type(
        (openai.APITimeoutError, openai.RateLimitError, openai.APIConnectionError)
    ),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def call_llm(
    messages: list[dict[str, str]],
    response_format: type[T],
    *,
    model: str | None = None,
    temperature: float = 0.3,
) -> T:
    """Call an OpenAI-compatible LLM and return a validated Pydantic object.

    Parameters
    ----------
    messages : list of {"role": ..., "content": ...} dicts.
    response_format : A ``BaseModel`` subclass. The SDK converts it to a
        JSON schema, sends it via the ``response_format`` parameter, and
        parses the reply back into the model automatically.
    model : Override the default model (env ``LLM_MODEL``).
    temperature : Sampling temperature.

    Returns
    -------
    An instance of *response_format* populated from the LLM response.

    Raises
    ------
    openai.LengthFinishReasonError
        If the response was truncated due to token limits.
    ValueError
        If the model refused to answer.
    """
    client = _get_client()
    resolved_model = model or _default_model()

    logger.debug(
        "call_llm  model=%s  response_format=%s  messages=%d",
        resolved_model,
        response_format.__name__,
        len(messages),
    )

    completion = await client.chat.completions.parse(
        model=resolved_model,
        messages=messages,
        response_format=response_format,
        temperature=temperature,
    )

    message = completion.choices[0].message

    if message.refusal:
        raise ValueError(f"LLM refused the request: {message.refusal}")

    if message.parsed is None:
        raise ValueError("LLM returned empty parsed content")

    logger.debug("call_llm  tokens=%s", completion.usage)
    return message.parsed
