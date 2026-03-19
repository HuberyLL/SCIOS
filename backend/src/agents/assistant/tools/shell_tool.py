"""Persistent Bash session tool — a stateful shell that preserves cwd and env
across successive commands, similar to OpenClaw's openshell."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from pydantic import BaseModel, Field

from src.agents.assistant.tools.base import BaseTool
from src.agents.assistant.tools.fs_sandbox import get_workspace_dir

logger = logging.getLogger(__name__)

_OUTPUT_CHAR_LIMIT = 2000
_DEFAULT_TIMEOUT = 120


class BashSession:
    """Manages a long-lived bash child process.

    Commands are delimited by a unique sentinel line so we can reliably
    detect when output for a given command ends.
    """

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def _ensure_started(self) -> asyncio.subprocess.Process:
        if self._proc is not None and self._proc.returncode is None:
            return self._proc
        workspace = get_workspace_dir()
        self._proc = await asyncio.create_subprocess_shell(
            "/bin/bash --norc",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(workspace),
        )
        logger.info("Started persistent bash session pid=%s cwd=%s", self._proc.pid, workspace)
        return self._proc

    async def run(self, command: str, timeout: int = _DEFAULT_TIMEOUT) -> str:
        """Execute *command* in the persistent shell and return its output."""
        async with self._lock:
            proc = await self._ensure_started()
            assert proc.stdin is not None
            assert proc.stdout is not None

            sentinel = f"__SENTINEL_{uuid.uuid4().hex[:12]}__"
            # Write the command followed by a sentinel echo that also captures $?
            payload = (
                f"{command}\n"
                f"__exit_code__=$?\n"
                f'echo "{sentinel} exit_code=$__exit_code__"\n'
            )
            proc.stdin.write(payload.encode())
            await proc.stdin.drain()

            output_lines: list[str] = []
            try:
                while True:
                    line_bytes = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=timeout
                    )
                    if not line_bytes:
                        # EOF — process died
                        break
                    line = line_bytes.decode("utf-8", errors="replace")
                    if sentinel in line:
                        break
                    output_lines.append(line)
            except asyncio.TimeoutError:
                logger.warning("Bash command timed out after %ds: %s", timeout, command[:200])
                proc.kill()
                await proc.wait()
                self._proc = None
                return f"[Command timed out after {timeout}s. Session reset.]"

            return "".join(output_lines)

    async def close(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()
            await self._proc.wait()
            self._proc = None


# Module-level singleton
_session = BashSession()


def get_bash_session() -> BashSession:
    return _session


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

class RunBashCommandArgs(BaseModel):
    command: str = Field(..., description="The bash command to execute.")
    timeout: int = Field(
        _DEFAULT_TIMEOUT,
        description="Maximum seconds to wait for the command to finish.",
    )


class RunBashCommandTool(BaseTool):
    name = "run_bash_command"
    description = (
        "Execute a command in a persistent bash session whose working directory "
        "starts in the workspace. The session preserves state (cwd, env vars) "
        "across calls."
    )
    args_schema = RunBashCommandArgs

    async def execute(self, **kwargs: Any) -> str:
        command: str = kwargs["command"]
        timeout: int = kwargs.get("timeout", _DEFAULT_TIMEOUT)

        session = get_bash_session()
        output = await session.run(command, timeout=timeout)

        if len(output) > _OUTPUT_CHAR_LIMIT:
            output = (
                f"[Output truncated... showing last {_OUTPUT_CHAR_LIMIT} chars]\n"
                + output[-_OUTPUT_CHAR_LIMIT:]
            )
        return output
