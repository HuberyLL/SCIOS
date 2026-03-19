"""Shared fixtures for the test suite."""

from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine
from tenacity import wait_none

import src.models.db as _db_mod
from src.agents.tools.s2_client import SemanticScholarClient


# ---------------------------------------------------------------------------
# Tools-layer helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fast_s2_retry():
    """Zero-wait retry for SemanticScholarClient methods in all tests."""
    targets = [SemanticScholarClient._get, SemanticScholarClient._post]
    originals = [t.retry.wait for t in targets]
    for t in targets:
        t.retry.wait = wait_none()
    yield
    for t, orig in zip(targets, originals):
        t.retry.wait = orig


# ---------------------------------------------------------------------------
# In-memory SQLite — replaces the production engine for every test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _test_db():
    """Provide a fresh in-memory SQLite database for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    _db_mod._engine = engine
    yield engine
    SQLModel.metadata.drop_all(engine)
    _db_mod._engine = None


@pytest.fixture(autouse=True)
def _clean_subscribers():
    """Ensure the in-process pub/sub dict is empty between tests."""
    from src.services.task_manager import _subscribers
    _subscribers.clear()
    yield
    _subscribers.clear()


# ---------------------------------------------------------------------------
# HTTP test client (httpx + ASGITransport)
# ---------------------------------------------------------------------------

@pytest.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
