"""Shared HTTP infrastructure: async client management, rate limiting, retry."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
MAX_KEEPALIVE = 10


# ---------------------------------------------------------------------------
# Async HTTP client context manager
# ---------------------------------------------------------------------------

@asynccontextmanager
async def managed_client(
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield a configured *httpx.AsyncClient* and close it on exit."""
    client = httpx.AsyncClient(
        timeout=timeout,
        limits=httpx.Limits(max_keepalive_connections=MAX_KEEPALIVE),
        headers=headers or {},
    )
    try:
        yield client
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Rate limiter (token-bucket style, per-endpoint)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Async token-bucket rate limiter keyed by endpoint prefix."""

    def __init__(self, rules: dict[str, tuple[int, float]] | None = None):
        """
        Parameters
        ----------
        rules : dict mapping endpoint substring -> (max_requests, period_seconds).
                Matched in order; first hit wins.  A special key ``"*"``
                serves as the default.
        """
        self._rules: dict[str, tuple[int, float]] = rules or {"*": (10, 1.0)}
        self._last_call: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _interval_for(self, endpoint: str) -> float:
        for substr, (_max_req, period) in self._rules.items():
            if substr != "*" and substr in endpoint:
                return period / _max_req
        fallback = self._rules.get("*", (10, 1.0))
        return fallback[1] / fallback[0]

    async def acquire(self, endpoint: str) -> None:
        if endpoint not in self._locks:
            self._locks[endpoint] = asyncio.Lock()
            self._last_call[endpoint] = 0.0

        async with self._locks[endpoint]:
            interval = self._interval_for(endpoint)
            elapsed = time.monotonic() - self._last_call[endpoint]
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)
            self._last_call[endpoint] = time.monotonic()


# ---------------------------------------------------------------------------
# Tenacity retry helper
# ---------------------------------------------------------------------------

def _is_retryable(exc: BaseException) -> bool:
    """Return True for HTTP 429 / 5xx so tenacity will retry."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout)):
        return True
    return False


api_retry = retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
"""Decorator: retry up to 3 times with exponential back-off on 429/5xx/timeout."""
