"""Dummy tool that returns the current system time — used to verify the
function-calling loop is working end-to-end."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from pydantic import BaseModel

from src.agents.assistant.tools.base import BaseTool

_TZ_OFFSETS: dict[str, timezone] = {
    "UTC": timezone.utc,
    "CST": timezone(timedelta(hours=8)),
    "EST": timezone(timedelta(hours=-5)),
    "PST": timezone(timedelta(hours=-8)),
    "JST": timezone(timedelta(hours=9)),
}


class GetSystemTimeArgs(BaseModel):
    timezone: str = "UTC"


class GetSystemTimeTool(BaseTool):
    name = "get_system_time"
    description = "Get the current system time. You can specify the timezone using the timezone parameter (supports UTC / CST / EST / PST / JST)."
    args_schema = GetSystemTimeArgs

    async def execute(self, **kwargs: Any) -> str:
        tz_name = kwargs.get("timezone", "UTC").upper()
        tz = _TZ_OFFSETS.get(tz_name, timezone.utc)
        now = datetime.now(tz)
        return f"{now.strftime('%Y-%m-%d %H:%M:%S')} {tz_name}"
