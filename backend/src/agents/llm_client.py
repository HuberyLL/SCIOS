"""Unified LLM client: async calls via litellm with structured Pydantic output."""

from __future__ import annotations

import asyncio
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

_semaphore: asyncio.Semaphore | None = None
_semaphore_limit: int = 0


def _get_semaphore() -> asyncio.Semaphore:
    """Lazily create a per-event-loop semaphore to cap concurrent LLM calls."""
    global _semaphore, _semaphore_limit
    cfg = get_settings()
    if _semaphore is None or _semaphore_limit != cfg.llm_max_concurrent:
        _semaphore_limit = cfg.llm_max_concurrent
        _semaphore = asyncio.Semaphore(_semaphore_limit)
    return _semaphore


def _default_model() -> str:
    return get_settings().llm_model


def _enforce_no_additional_properties(node: Any) -> None:
    """Recursively enforce strict-object constraints for OpenAI JSON schema.

    OpenAI strict JSON schema expects object nodes to explicitly define:
    - ``additionalProperties: false``
    - ``required`` including every key in ``properties``
    """
    if isinstance(node, dict):
        is_object = node.get("type") == "object" or "properties" in node
        if is_object:
            node.setdefault("additionalProperties", False)
            props = node.get("properties")
            if isinstance(props, dict):
                node["required"] = list(props.keys())

        # Traverse common JSON-schema containers.
        for key in ("properties", "$defs", "definitions", "patternProperties"):
            value = node.get(key)
            if isinstance(value, dict):
                for child in value.values():
                    _enforce_no_additional_properties(child)

        # Traverse union / composition operators.
        for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
            value = node.get(key)
            if isinstance(value, list):
                for child in value:
                    _enforce_no_additional_properties(child)

        # Traverse single-child schema fields.
        for key in ("items", "contains", "not", "if", "then", "else"):
            if key in node:
                _enforce_no_additional_properties(node[key])
        return

    if isinstance(node, list):
        for child in node:
            _enforce_no_additional_properties(child)


def _response_format_schema(response_format: type[T]) -> dict[str, Any]:
    """Build an OpenAI-style strict JSON schema response_format payload."""
    schema = response_format.model_json_schema()
    schema.pop("title", None)
    _enforce_no_additional_properties(schema)
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


# ---------------------------------------------------------------------------
# Retry + concurrency-gated LLM call
# ---------------------------------------------------------------------------


@retry(
    retry=retry_if_exception_type(
        (litellm.Timeout, litellm.RateLimitError, litellm.APIConnectionError)
    ),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
async def _call_llm_inner(
    messages: list[dict[str, str]],
    response_format: type[T],
    *,
    model: str | None = None,
    temperature: float = 0.3,
) -> T:
    cfg = get_settings()
    resolved_model = model or _default_model()

    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "response_format": _response_format_schema(response_format),
        "temperature": temperature,
        "num_retries": 0,
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


async def call_llm(
    messages: list[dict[str, str]],
    response_format: type[T],
    *,
    model: str | None = None,
    temperature: float = 0.3,
) -> T:
    """Call an LLM via litellm and return a validated Pydantic object.

    Concurrency is gated by a global semaphore (``llm_max_concurrent``).
    Retries are handled by tenacity only (OpenAI SDK retries disabled via
    ``num_retries=0``).
    """
    sem = _get_semaphore()
    logger.debug(
        "call_llm  model=%s  response_format=%s  messages=%d  sem_waiting=%d",
        model or _default_model(),
        response_format.__name__,
        len(messages),
        sem._value if hasattr(sem, "_value") else -1,
    )
    async with sem:
        return await _call_llm_inner(
            messages,
            response_format,
            model=model,
            temperature=temperature,
        )
