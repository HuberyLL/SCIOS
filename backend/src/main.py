"""SCIOS FastAPI application entry-point.

Start with::

    uvicorn src.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel

from src.api.v1.assistant import router as assistant_router
from src.api.v1.exploration import router as exploration_router
from src.api.v1.landscape import router as landscape_router
from src.api.v1.monitoring import router as monitoring_router
from src.models.db import get_engine
from src.services.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    import src.agents.assistant.tools  # noqa: F401 — trigger tool registration
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(
    title="SCIOS – Smart Research Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(exploration_router)
app.include_router(landscape_router)
app.include_router(monitoring_router)
app.include_router(assistant_router)
