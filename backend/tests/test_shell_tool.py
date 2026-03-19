"""Tests for RunBashCommandTool and RunPythonCodeTool."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.assistant.tools.python_repl import RunPythonCodeTool, reset_namespace
from src.agents.assistant.tools.shell_tool import BashSession, RunBashCommandTool


# ── Bash tool ───────────────────────────────────────────────────────────


class TestRunBashCommandTool:
    @pytest.fixture(autouse=True)
    def _patch_workspace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "src.agents.assistant.tools.shell_tool.get_workspace_dir",
            lambda: tmp_path,
        )
        self.workspace = tmp_path

    @pytest.fixture
    async def tool(self):
        session = BashSession()
        tool = RunBashCommandTool()
        original_getter = __import__(
            "src.agents.assistant.tools.shell_tool", fromlist=["get_bash_session"]
        ).get_bash_session

        import src.agents.assistant.tools.shell_tool as mod
        mod.get_bash_session = lambda: session

        yield tool

        await session.close()
        mod.get_bash_session = original_getter

    @pytest.mark.asyncio
    async def test_echo(self, tool):
        result = await tool.execute(command="echo hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_cwd_persistence(self, tool):
        (self.workspace / "mydir").mkdir()
        await tool.execute(command="cd mydir")
        result = await tool.execute(command="pwd")
        assert "mydir" in result

    @pytest.mark.asyncio
    async def test_env_persistence(self, tool):
        await tool.execute(command="export MY_VAR=42")
        result = await tool.execute(command="echo $MY_VAR")
        assert "42" in result

    @pytest.mark.asyncio
    async def test_output_truncation(self, tool):
        result = await tool.execute(command="python3 -c \"print('A' * 5000)\"")
        assert "[Output truncated" in result

    @pytest.mark.asyncio
    async def test_timeout(self, tool):
        result = await tool.execute(command="sleep 10", timeout=1)
        assert "timed out" in result


# ── Python REPL tool ────────────────────────────────────────────────────


class TestRunPythonCodeTool:
    @pytest.fixture(autouse=True)
    def _patch_workspace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "src.agents.assistant.tools.python_repl.get_workspace_dir",
            lambda: tmp_path,
        )

    @pytest.fixture(autouse=True)
    def _fresh_namespace(self):
        reset_namespace()
        yield
        reset_namespace()

    @pytest.fixture
    def tool(self):
        return RunPythonCodeTool()

    @pytest.mark.asyncio
    async def test_basic_print(self, tool):
        result = await tool.execute(code="print('hello from repl')")
        assert "hello from repl" in result

    @pytest.mark.asyncio
    async def test_state_persistence(self, tool):
        await tool.execute(code="x = 42")
        result = await tool.execute(code="print(x)")
        assert "42" in result

    @pytest.mark.asyncio
    async def test_import_persistence(self, tool):
        await tool.execute(code="import math")
        result = await tool.execute(code="print(math.pi)")
        assert "3.14" in result

    @pytest.mark.asyncio
    async def test_exception_captured(self, tool):
        result = await tool.execute(code="1 / 0")
        assert "ZeroDivisionError" in result

    @pytest.mark.asyncio
    async def test_no_output(self, tool):
        result = await tool.execute(code="y = 10")
        assert result == "(no output)"

    @pytest.mark.asyncio
    async def test_output_truncation(self, tool):
        result = await tool.execute(code="print('B' * 5000)")
        assert "[Output truncated" in result

    @pytest.mark.asyncio
    async def test_workspace_variable(self, tool, tmp_path: Path):
        result = await tool.execute(code="print(__workspace__)")
        assert str(tmp_path) in result
