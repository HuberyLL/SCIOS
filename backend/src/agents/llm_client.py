"""Unified LLM client: async calls via litellm with structured Pydantic output."""

from __future__ import annotations

import logging
import re
from typing import Any, TypeVar

import litellm
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


def _default_model() -> str:
    return get_settings().llm_model


def _response_format_schema(response_format: type[T]) -> dict[str, Any]:
    """Build an OpenAI-style strict JSON schema response_format payload."""
    schema = response_format.model_json_schema()
    schema.pop("title", None)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": response_format.__name__,
            "schema": schema,
            "strict": True,
        },
    }


def _extract_message_text(content: Any) -> str:
    """Extract text from provider-normalized content payloads."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
            else:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(content)


def _extract_json_candidate(raw: str) -> str:
    """Try to extract a JSON object from markdown/code-fenced text."""
    text = raw.strip()
    if not text:
        return text

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1].strip()
    return text


def _parse_structured_message(message: Any, response_format: type[T]) -> T:
    refusal = getattr(message, "refusal", None)
    if refusal:
        raise ValueError(f"LLM refused the request: {refusal}")

    raw_text = _extract_message_text(getattr(message, "content", None))
    if not raw_text:
        raise ValueError("LLM returned empty content")

    try:
        return response_format.model_validate_json(raw_text)
    except Exception:
        candidate = _extract_json_candidate(raw_text)
        if candidate != raw_text:
            try:
                return response_format.model_validate_json(candidate)
            except Exception:
                pass
        raise ValueError("LLM returned non-JSON or schema-invalid content")


@retry(
    retry=retry_if_exception_type(
        (litellm.Timeout, litellm.RateLimitError, litellm.APIConnectionError)
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
    """Call an LLM via litellm and return a validated Pydantic object.

    Parameters
    ----------
    messages : list of {"role": ..., "content": ...} dicts.
    response_format : A ``BaseModel`` subclass. Sent as strict JSON schema
        constraints, then validated back into the model.
    model : Override the default model (env ``LLM_MODEL``).
    temperature : Sampling temperature.

    Returns
    -------
    An instance of *response_format* populated from the LLM response.

    Raises
    ------
    ValueError
        If the model refused to answer or returned schema-invalid content.
    """
    cfg = get_settings()
    resolved_model = model or _default_model()

    logger.debug(
        "call_llm  model=%s  response_format=%s  messages=%d",
        resolved_model,
        response_format.__name__,
        len(messages),
    )

    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "response_format": _response_format_schema(response_format),
        "temperature": temperature,
    }
    if cfg.llm_api_key:
        kwargs["api_key"] = cfg.llm_api_key
    if cfg.llm_base_url:
        kwargs["api_base"] = cfg.llm_base_url

    completion = await litellm.acompletion(**kwargs)
    if not completion.choices:
        raise ValueError("LLM returned no choices")
    message = completion.choices[0].message

    logger.debug("call_llm  tokens=%s", completion.usage)
    return _parse_structured_message(message, response_format)
