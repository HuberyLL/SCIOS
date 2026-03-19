"""In-process Python REPL with a persistent namespace across invocations.

This allows the LLM to build up state incrementally — for example, load a
DataFrame once and query it in subsequent calls — without the overhead of
re-importing libraries every time.
"""

from __future__ import annotations

import contextlib
import io
import traceback
from typing import Any

from pydantic import BaseModel, Field

from src.agents.assistant.tools.base import BaseTool
from src.agents.assistant.tools.fs_sandbox import get_workspace_dir

_OUTPUT_CHAR_LIMIT = 2000

_namespace: dict[str, Any] = {"__builtins__": __builtins__}
_initialized = False


def _ensure_namespace() -> dict[str, Any]:
    global _initialized
    if not _initialized:
        _namespace["__workspace__"] = str(get_workspace_dir())
        _initialized = True
    return _namespace


def reset_namespace() -> None:
    """Reset the REPL namespace — mainly useful for tests."""
    global _initialized
    _namespace.clear()
    _namespace["__builtins__"] = __builtins__
    _initialized = False


class RunPythonCodeArgs(BaseModel):
    code: str = Field(..., description="Python code to execute in the persistent REPL.")


class RunPythonCodeTool(BaseTool):
    name = "run_python_code"
    description = (
        "Execute Python code in a persistent in-process REPL. "
        "Variables and imports are preserved across calls. "
        "Print output and the repr of the last expression are captured."
    )
    args_schema = RunPythonCodeArgs

    async def execute(self, **kwargs: Any) -> str:
        code: str = kwargs["code"]
        ns = _ensure_namespace()

        stdout_buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout_buf):
                exec(compile(code, "<assistant-repl>", "exec"), ns)
        except Exception:
            stdout_buf.write(traceback.format_exc())

        output = stdout_buf.getvalue()
        if len(output) > _OUTPUT_CHAR_LIMIT:
            output = (
                f"[Output truncated... showing last {_OUTPUT_CHAR_LIMIT} chars]\n"
                + output[-_OUTPUT_CHAR_LIMIT:]
            )
        return output if output else "(no output)"
