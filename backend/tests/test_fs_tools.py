"""Tests for the workspace sandbox and file-system tools."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.agents.assistant.tools.fs_sandbox import resolve_and_check_path
from src.agents.assistant.tools.fs_tools import (
    EditFileTool,
    GlobSearchTool,
    ReadFileTool,
    WriteFileTool,
)


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the sandbox at a temporary directory for every test."""
    monkeypatch.setattr(
        "src.agents.assistant.tools.fs_sandbox.get_workspace_dir",
        lambda: tmp_path,
    )
    # Also patch inside fs_tools which imports the function at module level
    monkeypatch.setattr(
        "src.agents.assistant.tools.fs_tools.get_workspace_dir",
        lambda: tmp_path,
    )
    return tmp_path


# ── resolve_and_check_path ──────────────────────────────────────────────


class TestResolveAndCheckPath:
    def test_valid_relative_path(self, tmp_path: Path):
        (tmp_path / "hello.txt").write_text("hi")
        result = resolve_and_check_path("hello.txt")
        assert result == tmp_path / "hello.txt"

    def test_nested_relative_path(self, tmp_path: Path):
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        (sub / "data.csv").write_text("1,2")
        result = resolve_and_check_path("a/b/data.csv")
        assert result == sub / "data.csv"

    def test_rejects_absolute_path(self):
        with pytest.raises(PermissionError, match="absolute paths"):
            resolve_and_check_path("/etc/passwd")

    def test_rejects_traversal(self):
        with pytest.raises(PermissionError, match="outside the workspace"):
            resolve_and_check_path("../../etc/passwd")

    def test_rejects_dot_dot(self):
        with pytest.raises(PermissionError, match="outside the workspace"):
            resolve_and_check_path("../secret.txt")

    def test_rejects_symlink_escape(self, tmp_path: Path):
        outside = tmp_path.parent / "outside_file.txt"
        outside.write_text("secret")
        link = tmp_path / "evil_link"
        link.symlink_to(outside)
        with pytest.raises(PermissionError, match="outside the workspace"):
            resolve_and_check_path("evil_link")
        outside.unlink()


# ── ReadFileTool ────────────────────────────────────────────────────────


class TestReadFileTool:
    @pytest.fixture
    def tool(self):
        return ReadFileTool()

    @pytest.mark.asyncio
    async def test_read_normal_file(self, tool, tmp_path: Path):
        (tmp_path / "note.txt").write_text("hello world")
        result = await tool.execute(path="note.txt")
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_read_large_file_truncated(self, tool, tmp_path: Path):
        content = "x" * (60 * 1024)
        (tmp_path / "big.txt").write_text(content)
        result = await tool.execute(path="big.txt")
        assert "[Truncated:" in result
        assert "50KB" in result

    @pytest.mark.asyncio
    async def test_read_missing_file(self, tool):
        with pytest.raises(FileNotFoundError):
            await tool.execute(path="no_such_file.txt")


# ── WriteFileTool ───────────────────────────────────────────────────────


class TestWriteFileTool:
    @pytest.fixture
    def tool(self):
        return WriteFileTool()

    @pytest.mark.asyncio
    async def test_write_creates_file(self, tool, tmp_path: Path):
        result = await tool.execute(path="output.txt", content="data here")
        assert "Successfully" in result
        assert (tmp_path / "output.txt").read_text() == "data here"

    @pytest.mark.asyncio
    async def test_write_creates_parent_dirs(self, tool, tmp_path: Path):
        await tool.execute(path="deep/nested/dir/file.txt", content="nested")
        assert (tmp_path / "deep" / "nested" / "dir" / "file.txt").read_text() == "nested"


# ── EditFileTool ────────────────────────────────────────────────────────


class TestEditFileTool:
    @pytest.fixture
    def tool(self):
        return EditFileTool()

    @pytest.mark.asyncio
    async def test_edit_single_occurrence(self, tool, tmp_path: Path):
        (tmp_path / "code.py").write_text("x = 1\ny = 2\n")
        result = await tool.execute(path="code.py", old_string="x = 1", new_string="x = 42")
        assert "Successfully" in result
        assert (tmp_path / "code.py").read_text() == "x = 42\ny = 2\n"

    @pytest.mark.asyncio
    async def test_edit_not_found(self, tool, tmp_path: Path):
        (tmp_path / "code.py").write_text("x = 1\n")
        with pytest.raises(ValueError, match="not found"):
            await tool.execute(path="code.py", old_string="z = 99", new_string="z = 0")

    @pytest.mark.asyncio
    async def test_edit_ambiguous(self, tool, tmp_path: Path):
        (tmp_path / "code.py").write_text("a = 1\na = 1\n")
        with pytest.raises(ValueError, match="appears 2 times"):
            await tool.execute(path="code.py", old_string="a = 1", new_string="a = 2")

    @pytest.mark.asyncio
    async def test_edit_missing_file(self, tool):
        with pytest.raises(FileNotFoundError):
            await tool.execute(path="nope.py", old_string="x", new_string="y")


# ── GlobSearchTool ──────────────────────────────────────────────────────


class TestGlobSearchTool:
    @pytest.fixture
    def tool(self):
        return GlobSearchTool()

    @pytest.mark.asyncio
    async def test_glob_finds_files(self, tool, tmp_path: Path):
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.py").write_text("")
        result = await tool.execute(pattern="**/*.py")
        assert "a.py" in result
        assert "b.py" in result
        assert "sub/c.py" in result

    @pytest.mark.asyncio
    async def test_glob_no_match(self, tool):
        result = await tool.execute(pattern="**/*.xyz")
        assert "No files matched" in result

    @pytest.mark.asyncio
    async def test_glob_truncation(self, tool, tmp_path: Path):
        for i in range(110):
            (tmp_path / f"file_{i:03d}.txt").write_text("")
        result = await tool.execute(pattern="*.txt")
        assert "[Truncated:" in result
