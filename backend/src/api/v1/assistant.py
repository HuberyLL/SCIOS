"""Assistant-mode API: REST endpoints for session management and a
WebSocket endpoint for real-time streaming chat."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from src.agents.assistant.runner import AssistantRunner
from src.models.assistant import AssistantMessage, AssistantSession, MessageRole
from src.models.db import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


# ------------------------------------------------------------------
# Request / Response schemas
# ------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    title: str = "New Chat"


class SessionOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class MessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    created_at: str


class SessionDetailOut(BaseModel):
    session: SessionOut
    messages: list[MessageOut]


class SessionListOut(BaseModel):
    sessions: list[SessionOut]


# ------------------------------------------------------------------
# REST: sessions CRUD
# ------------------------------------------------------------------

@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(body: CreateSessionRequest) -> SessionOut:
    session = AssistantSession(title=body.title)
    with Session(get_engine()) as db:
        db.add(session)
        db.commit()
        db.refresh(session)
    return SessionOut(
        id=session.id,
        title=session.title,
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )


@router.get("/sessions", response_model=SessionListOut)
def list_sessions() -> SessionListOut:
    with Session(get_engine()) as db:
        stmt = select(AssistantSession).order_by(
            AssistantSession.updated_at.desc()  # type: ignore[union-attr]
        )
        rows = db.exec(stmt).all()
    return SessionListOut(
        sessions=[
            SessionOut(
                id=r.id,
                title=r.title,
                created_at=r.created_at.isoformat(),
                updated_at=r.updated_at.isoformat(),
            )
            for r in rows
        ]
    )


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
def get_session(session_id: str) -> SessionDetailOut:
    with Session(get_engine()) as db:
        session = db.get(AssistantSession, session_id)
        if session is None:
            raise HTTPException(404, "Session not found")
        msgs = db.exec(
            select(AssistantMessage)
            .where(AssistantMessage.session_id == session_id)
            .order_by(AssistantMessage.created_at)  # type: ignore[arg-type]
        ).all()
    return SessionDetailOut(
        session=SessionOut(
            id=session.id,
            title=session.title,
            created_at=session.created_at.isoformat(),
            updated_at=session.updated_at.isoformat(),
        ),
        messages=[
            MessageOut(
                id=m.id,
                session_id=m.session_id,
                role=m.role.value,
                content=m.content,
                tool_calls=m.tool_calls,
                tool_call_id=m.tool_call_id,
                created_at=m.created_at.isoformat(),
            )
            for m in msgs
        ],
    )


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str) -> None:
    with Session(get_engine()) as db:
        session = db.get(AssistantSession, session_id)
        if session is None:
            raise HTTPException(404, "Session not found")
        msgs = db.exec(
            select(AssistantMessage).where(
                AssistantMessage.session_id == session_id
            )
        ).all()
        for m in msgs:
            db.delete(m)
        db.delete(session)
        db.commit()


# ------------------------------------------------------------------
# WebSocket: streaming chat
# ------------------------------------------------------------------

@router.websocket("/ws/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str) -> None:
    with Session(get_engine()) as db:
        session = db.get(AssistantSession, session_id)
    if session is None:
        await websocket.close(code=4004, reason="Session not found")
        return

    await websocket.accept()
    logger.info("WebSocket connected for session %s", session_id)

    try:
        while True:
            data = await websocket.receive_json()
            user_input = data.get("content", "")
            if not user_input:
                await websocket.send_json(
                    {"event": "error", "data": {"message": "Empty message"}}
                )
                continue

            runner = AssistantRunner(session_id)
            async for event in runner.stream_chat(user_input):
                await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %s", session_id)
    except Exception:
        logger.exception("WebSocket error for session %s", session_id)
