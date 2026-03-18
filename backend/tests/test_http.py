"""T1-T3: Tests for _http.py — retry decorator and rate limiter."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
import respx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_none,
)

from src.agents.tools._http import RateLimiter, _is_retryable, managed_client

_fast_retry = retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_none(),
    stop=stop_after_attempt(3),
    reraise=True,
)


# ------------------------------------------------------------------
# T1: Graceful retry — 502 → 429 → 200
# ------------------------------------------------------------------

async def test_t1_retry_succeeds_after_transient_errors():
    """api_retry retries on 502 and 429, then returns the 200 payload."""

    @_fast_retry
    async def _fetch(url: str) -> dict:
        async with managed_client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    url = "https://test.example.com/api"
    with respx.mock:
        route = respx.get(url).mock(
            side_effect=[
                httpx.Response(502, text="Bad Gateway"),
                httpx.Response(429, text="Rate Limited"),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        result = await _fetch(url)

    assert result == {"ok": True}
    assert route.call_count == 3


# ------------------------------------------------------------------
# T2: Final failure — exhaust retries then raise
# ------------------------------------------------------------------

async def test_t2_retry_exhausted_raises():
    """After 3 consecutive timeouts, the exception propagates."""

    call_count = 0

    @_fast_retry
    async def _fetch(url: str) -> dict:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectTimeout("simulated timeout")

    with pytest.raises(httpx.ConnectTimeout):
        await _fetch("https://test.example.com/api")

    assert call_count == 3


# ------------------------------------------------------------------
# T3: Rate limiter enforces intervals
# ------------------------------------------------------------------

async def test_t3_rate_limiter_enforces_interval():
    """5 concurrent acquires on a 1-req/s endpoint take >= 4 intervals."""

    limiter = RateLimiter(rules={"/search": (1, 1.0), "*": (10, 1.0)})

    start = time.monotonic()
    await asyncio.gather(*(limiter.acquire("/search") for _ in range(5)))
    elapsed = time.monotonic() - start

    assert elapsed >= 3.8, f"Expected >= ~4s, got {elapsed:.2f}s"
