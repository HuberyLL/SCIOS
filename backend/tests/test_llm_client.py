"""Unit tests for structured LLM client behavior."""

from __future__ import annotations

from types import SimpleNamespace

import litellm
import pytest
from pydantic import BaseModel

from src.agents.llm_client import _response_format_schema, call_llm


class _Plan(BaseModel):
    query: str
    top_k: int


class _NestedMeta(BaseModel):
    language: str
    tags: list[str]


class _NestedPlan(BaseModel):
    query: str
    meta: _NestedMeta
    variants: list[_NestedMeta]


def _completion(content: str | None, *, refusal: str | None = None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, refusal=refusal))],
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )


@pytest.mark.asyncio
async def test_call_llm_parses_json_content(mocker) -> None:
    mocker.patch(
        "src.agents.llm_client.litellm.acompletion",
        return_value=_completion('{"query":"gnn","top_k":5}'),
    )

    out = await call_llm(
        messages=[{"role": "user", "content": "plan it"}],
        response_format=_Plan,
    )

    assert out.query == "gnn"
    assert out.top_k == 5


@pytest.mark.asyncio
async def test_call_llm_parses_fenced_json_content(mocker) -> None:
    mocker.patch(
        "src.agents.llm_client.litellm.acompletion",
        return_value=_completion(
            "Here is the result:\n```json\n{\"query\":\"graph\",\"top_k\":3}\n```"
        ),
    )

    out = await call_llm(
        messages=[{"role": "user", "content": "plan it"}],
        response_format=_Plan,
    )

    assert out.query == "graph"
    assert out.top_k == 3


@pytest.mark.asyncio
async def test_call_llm_raises_on_empty_content(mocker) -> None:
    mocker.patch(
        "src.agents.llm_client.litellm.acompletion",
        return_value=_completion(None),
    )

    with pytest.raises(ValueError, match="empty content"):
        await call_llm(
            messages=[{"role": "user", "content": "plan it"}],
            response_format=_Plan,
        )


@pytest.mark.asyncio
async def test_call_llm_retries_on_rate_limit(mocker) -> None:
    calls = {"n": 0}

    async def _fake_acompletion(**_):
        calls["n"] += 1
        if calls["n"] == 1:
            raise litellm.RateLimitError(
                message="rate limit",
                llm_provider="openai",
                model="gpt-4o",
                response=None,
            )
        return _completion('{"query":"retry-ok","top_k":2}')

    mocker.patch("src.agents.llm_client.litellm.acompletion", side_effect=_fake_acompletion)

    out = await call_llm(
        messages=[{"role": "user", "content": "plan it"}],
        response_format=_Plan,
    )

    assert calls["n"] == 2
    assert out.query == "retry-ok"
    assert out.top_k == 2


def test_response_format_schema_sets_additional_properties_false_recursively() -> None:
    wrapped = _response_format_schema(_NestedPlan)
    schema = wrapped["json_schema"]["schema"]

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"query", "meta", "variants"}
    assert schema["$defs"]["_NestedMeta"]["additionalProperties"] is False
    assert set(schema["$defs"]["_NestedMeta"]["required"]) == {"language", "tags"}
