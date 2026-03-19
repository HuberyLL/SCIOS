"""Workspace sandbox: confine all file operations to a safe directory."""

from __future__ import annotations

from pathlib import Path

from src.core.config import get_settings

_PROJECT_ROOT = Path(__file__).resolve().parents[4]  # backend/src/agents/assistant/tools -> project root


def get_workspace_dir() -> Path:
    """Return the resolved workspace directory, creating it if absent."""
    raw = get_settings().assistant_workspace_dir
    workspace = Path(raw) if Path(raw).is_absolute() else _PROJECT_ROOT / raw
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def resolve_and_check_path(relative_path: str) -> Path:
    """Resolve *relative_path* inside the workspace and verify it stays within bounds.

    Raises ``PermissionError`` when the resolved path escapes the sandbox.
    """
    if Path(relative_path).is_absolute():
        raise PermissionError("Access denied: absolute paths are not allowed.")

    workspace = get_workspace_dir()
    resolved = (workspace / relative_path).resolve()

    if not resolved.is_relative_to(workspace):
        raise PermissionError("Access denied: path is outside the workspace sandbox.")

    return resolved
