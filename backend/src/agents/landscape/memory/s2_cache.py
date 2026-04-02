"""Layer 1: File-based cache for Semantic Scholar API responses.

Each response is stored as a JSON file keyed by SHA-256 of the request
signature (endpoint + sorted params).  TTL is endpoint-specific because
paper metadata changes slowly while search results update more often.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from src.core.config import get_settings

logger = logging.getLogger(__name__)

_TTL_SECONDS: dict[str, int] = {
    "/paper/search": 86_400,           # 1 day
    "/paper/batch": 86_400 * 3,        # 3 days
    "/recommendations": 86_400,        # 1 day
}
_TTL_PATTERN: list[tuple[str, int]] = [
    ("/citations", 86_400 * 3),        # 3 days
    ("/references", 86_400 * 3),       # 3 days
    ("/author/", 86_400 * 3),          # 3 days
    ("/paper/", 86_400 * 7),           # 7 days (single paper detail)
]
_TTL_DEFAULT = 86_400                  # 1 day fallback


def _ttl_for_endpoint(endpoint: str) -> int:
    if endpoint in _TTL_SECONDS:
        return _TTL_SECONDS[endpoint]
    for pattern, ttl in _TTL_PATTERN:
        if pattern in endpoint:
            return ttl
    return _TTL_DEFAULT


def _cache_key(endpoint: str, params: dict[str, Any] | None, body: dict[str, Any] | None) -> str:
    """Deterministic SHA-256 key from request signature."""
    parts = [endpoint]
    if params:
        parts.append(json.dumps(params, sort_keys=True, default=str))
    if body:
        parts.append(json.dumps(body, sort_keys=True, default=str))
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


class S2Cache:
    """File-system cache for S2 API JSON responses."""

    def __init__(self, cache_dir: str | Path | None = None, *, enabled: bool | None = None) -> None:
        settings = get_settings()
        self._enabled = enabled if enabled is not None else settings.s2_cache_enabled
        base = Path(cache_dir) if cache_dir else Path(settings.cache_dir)
        self._dir = base / "s2"
        self._max_bytes = settings.s2_cache_max_mb * 1024 * 1024
        if self._enabled:
            self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def cache_dir(self) -> Path:
        return self._dir

    def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict | list | None:
        """Return cached response or ``None`` on miss / expired."""
        if not self._enabled:
            return None
        key = _cache_key(endpoint, params, body)
        path = self._dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            path.unlink(missing_ok=True)
            return None

        cached_at = raw.get("cached_at", 0)
        ttl = raw.get("ttl_seconds", _TTL_DEFAULT)
        if time.time() - cached_at > ttl:
            path.unlink(missing_ok=True)
            return None

        os.utime(path)
        return raw.get("data")

    def put(
        self,
        endpoint: str,
        data: dict | list,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> None:
        """Write *data* to cache."""
        if not self._enabled:
            return
        key = _cache_key(endpoint, params, body)
        path = self._dir / f"{key}.json"
        ttl = _ttl_for_endpoint(endpoint)
        envelope = {
            "cached_at": time.time(),
            "ttl_seconds": ttl,
            "endpoint": endpoint,
            "data": data,
        }
        try:
            path.write_text(json.dumps(envelope, default=str), encoding="utf-8")
        except OSError:
            logger.warning("Failed to write S2 cache file: %s", path)
        self._maybe_evict()

    def _maybe_evict(self) -> None:
        """LRU eviction when total cache size exceeds limit."""
        try:
            files = list(self._dir.glob("*.json"))
        except OSError:
            return
        total = sum(f.stat().st_size for f in files if f.is_file())
        if total <= self._max_bytes:
            return
        files.sort(key=lambda f: f.stat().st_atime)
        removed = 0
        for f in files:
            if total <= self._max_bytes * 0.8:
                break
            try:
                size = f.stat().st_size
                f.unlink()
                total -= size
                removed += 1
            except OSError:
                continue
        if removed:
            logger.info("S2 cache eviction: removed %d files", removed)

    def clear(self) -> int:
        """Remove all cached files. Returns count of files removed."""
        count = 0
        for f in self._dir.glob("*.json"):
            try:
                f.unlink()
                count += 1
            except OSError:
                continue
        return count
