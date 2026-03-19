"""File-system tools: read, write, edit and search files inside the workspace."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.agents.assistant.tools.base import BaseTool
from src.agents.assistant.tools.fs_sandbox import get_workspace_dir, resolve_and_check_path

_MAX_READ_BYTES = 50 * 1024  # 50 KB
_MAX_GLOB_RESULTS = 100


# ---------------------------------------------------------------------------
# Pydantic arg schemas
# ---------------------------------------------------------------------------

class ReadFileArgs(BaseModel):
    path: str = Field(..., description="Relative path to the file inside the workspace.")


class WriteFileArgs(BaseModel):
    path: str = Field(..., description="Relative path to the file inside the workspace.")
    content: str = Field(..., description="Content to write into the file.")


class EditFileArgs(BaseModel):
    path: str = Field(..., description="Relative path to the file inside the workspace.")
    old_string: str = Field(..., description="Exact substring to find in the file.")
    new_string: str = Field(..., description="Replacement string.")


class GlobSearchArgs(BaseModel):
    pattern: str = Field(..., description="Glob pattern such as '**/*.py' or 'data/*.csv'.")


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "Read the contents of a file inside the workspace. "
        "The path must be relative to the workspace root."
    )
    args_schema = ReadFileArgs

    async def execute(self, **kwargs: Any) -> str:
        path = kwargs["path"]
        resolved = resolve_and_check_path(path)

        if not resolved.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        size = resolved.stat().st_size
        try:
            raw = resolved.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"Cannot read {path}: {exc}") from exc

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")

        if size > _MAX_READ_BYTES:
            text = text[: _MAX_READ_BYTES]
            return f"{text}\n\n[Truncated: showing first 50KB of {size} bytes]"
        return text


class WriteFileTool(BaseTool):
    name = "write_file"
    description = (
        "Write (or overwrite) a file inside the workspace. "
        "Parent directories are created automatically."
    )
    args_schema = WriteFileArgs

    async def execute(self, **kwargs: Any) -> str:
        path = kwargs["path"]
        content: str = kwargs["content"]
        resolved = resolve_and_check_path(path)

        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"Successfully written to {path}"


class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "Replace one exact occurrence of old_string with new_string in a file. "
        "Fails if old_string is not found or is ambiguous (appears more than once)."
    )
    args_schema = EditFileArgs

    async def execute(self, **kwargs: Any) -> str:
        path = kwargs["path"]
        old_string: str = kwargs["old_string"]
        new_string: str = kwargs["new_string"]

        resolved = resolve_and_check_path(path)
        if not resolved.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        text = resolved.read_text(encoding="utf-8")
        count = text.count(old_string)

        if count == 0:
            raise ValueError(
                f"old_string not found in {path}. "
                "Make sure the string matches exactly (including whitespace and newlines)."
            )
        if count > 1:
            raise ValueError(
                f"old_string appears {count} times in {path}. "
                "Provide more surrounding context to make the match unique."
            )

        new_text = text.replace(old_string, new_string, 1)
        resolved.write_text(new_text, encoding="utf-8")
        return f"Successfully edited {path}"


class GlobSearchTool(BaseTool):
    name = "glob_search"
    description = (
        "Search the workspace for files matching a glob pattern (e.g. '**/*.py'). "
        "Returns a list of relative paths, capped at 100 results."
    )
    args_schema = GlobSearchArgs

    async def execute(self, **kwargs: Any) -> str:
        pattern: str = kwargs["pattern"]
        workspace = get_workspace_dir()

        matches = sorted(
            p.relative_to(workspace).as_posix()
            for p in workspace.glob(pattern)
            if p.is_file()
        )

        total = len(matches)
        truncated = matches[:_MAX_GLOB_RESULTS]

        if not truncated:
            return "No files matched the pattern."

        result = "\n".join(truncated)
        if total > _MAX_GLOB_RESULTS:
            result += f"\n\n[Truncated: showing {_MAX_GLOB_RESULTS} of {total} matches]"
        return result
