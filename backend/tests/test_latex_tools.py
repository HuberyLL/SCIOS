"""Tests for CompileLatexTool and ParseCSVLogTool."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.agents.assistant.tools.experiment_tools import ParseCSVLogTool
from src.agents.assistant.tools.latex_tools import CompileLatexTool


# ── Shared workspace fixture ────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "src.agents.assistant.tools.fs_sandbox.get_workspace_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "src.agents.assistant.tools.latex_tools.get_workspace_dir",
        lambda: tmp_path,
    )
    return tmp_path


# ── CompileLatexTool ────────────────────────────────────────────────────


class TestCompileLatexTool:
    @pytest.fixture
    def tool(self):
        return CompileLatexTool()

    @pytest.mark.asyncio
    async def test_file_not_found(self, tool):
        result = await tool.execute(tex_file_path="missing.tex")
        assert "file not found" in result

    @pytest.mark.asyncio
    async def test_rejects_non_tex(self, tool, tmp_path: Path):
        (tmp_path / "notes.txt").write_text("hello")
        result = await tool.execute(tex_file_path="notes.txt")
        assert "expected a .tex file" in result

    @pytest.mark.asyncio
    async def test_pdflatex_not_installed(self, tool, tmp_path: Path, monkeypatch):
        (tmp_path / "paper.tex").write_text(r"\documentclass{article}\begin{document}Hi\end{document}")

        monkeypatch.setattr(
            "src.agents.assistant.tools.latex_tools._resolve_pdflatex_executable",
            lambda env: None,
        )

        result = await tool.execute(tex_file_path="paper.tex")
        assert "pdflatex is not installed" in result

    @pytest.mark.asyncio
    async def test_uses_resolved_pdflatex_binary(self, tool, tmp_path: Path, monkeypatch):
        tex_file = tmp_path / "paper.tex"
        tex_file.write_text(r"\documentclass{article}\begin{document}Hi\end{document}")

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.returncode = 0

        seen_commands: list[str] = []

        async def _fake_exec(*args, **kwargs):
            seen_commands.append(args[0])
            (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
            return mock_proc

        monkeypatch.setattr(
            "src.agents.assistant.tools.latex_tools._resolve_pdflatex_executable",
            lambda env: "/custom/pdflatex",
        )
        monkeypatch.setattr(
            "src.agents.assistant.tools.latex_tools.asyncio.create_subprocess_exec",
            _fake_exec,
        )

        result = await tool.execute(tex_file_path="paper.tex")
        assert "Success" in result
        assert seen_commands
        assert all(command == "/custom/pdflatex" for command in seen_commands)

    @pytest.mark.asyncio
    async def test_successful_compilation(self, tool, tmp_path: Path, monkeypatch):
        tex_file = tmp_path / "paper.tex"
        tex_file.write_text(r"\documentclass{article}\begin{document}Hi\end{document}")

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.returncode = 0

        async def _fake_exec(*args, **kwargs):
            (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
            return mock_proc

        monkeypatch.setattr(
            "src.agents.assistant.tools.latex_tools.asyncio.create_subprocess_exec",
            _fake_exec,
        )

        result = await tool.execute(tex_file_path="paper.tex")
        assert "Success" in result
        assert "paper.pdf" in result

    @pytest.mark.asyncio
    async def test_compilation_failure_with_log(self, tool, tmp_path: Path, monkeypatch):
        tex_file = tmp_path / "bad.tex"
        tex_file.write_text(r"\invalid")

        log_file = tmp_path / "bad.log"
        log_file.write_text("! Undefined control sequence.\n" * 50)

        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=1)
        mock_proc.returncode = 1

        async def _fake_exec(*args, **kwargs):
            return mock_proc

        monkeypatch.setattr(
            "src.agents.assistant.tools.latex_tools.asyncio.create_subprocess_exec",
            _fake_exec,
        )

        result = await tool.execute(tex_file_path="bad.tex")
        assert "compilation failed" in result
        assert "Undefined control sequence" in result

    @pytest.mark.asyncio
    async def test_absolute_path_rejected(self, tool):
        with pytest.raises(PermissionError, match="absolute paths"):
            await tool.execute(tex_file_path="/etc/evil.tex")


# ── ParseCSVLogTool ─────────────────────────────────────────────────────


class TestParseCSVLogTool:
    @pytest.fixture
    def tool(self):
        return ParseCSVLogTool()

    @pytest.mark.asyncio
    async def test_basic_csv(self, tool, tmp_path: Path):
        csv = tmp_path / "loss.csv"
        csv.write_text("epoch,train_loss,val_loss\n1,0.9,0.95\n2,0.7,0.75\n3,0.5,0.55\n")

        result = await tool.execute(csv_path="loss.csv")
        assert "3 rows" in result
        assert "train_loss" in result
        assert "0.5" in result

    @pytest.mark.asyncio
    async def test_column_filtering(self, tool, tmp_path: Path):
        csv = tmp_path / "metrics.csv"
        csv.write_text("epoch,loss,acc,lr\n1,0.9,0.6,0.001\n2,0.5,0.8,0.001\n")

        result = await tool.execute(csv_path="metrics.csv", columns=["epoch", "loss"])
        assert "loss" in result
        assert "lr" not in result

    @pytest.mark.asyncio
    async def test_missing_columns_warned(self, tool, tmp_path: Path):
        csv = tmp_path / "data.csv"
        csv.write_text("a,b\n1,2\n3,4\n")

        result = await tool.execute(csv_path="data.csv", columns=["a", "nonexistent"])
        assert "Warning" in result
        assert "nonexistent" in result

    @pytest.mark.asyncio
    async def test_all_columns_missing(self, tool, tmp_path: Path):
        csv = tmp_path / "data.csv"
        csv.write_text("a,b\n1,2\n")

        result = await tool.execute(csv_path="data.csv", columns=["x", "y"])
        assert "none of the requested columns exist" in result

    @pytest.mark.asyncio
    async def test_file_not_found(self, tool):
        result = await tool.execute(csv_path="nope.csv")
        assert "file not found" in result

    @pytest.mark.asyncio
    async def test_empty_csv(self, tool, tmp_path: Path):
        csv = tmp_path / "empty.csv"
        csv.write_text("epoch,loss\n")

        result = await tool.execute(csv_path="empty.csv")
        assert "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_tail_rows(self, tool, tmp_path: Path):
        lines = ["epoch,loss"] + [f"{i},{1.0 / (i + 1):.4f}" for i in range(50)]
        csv = tmp_path / "long.csv"
        csv.write_text("\n".join(lines) + "\n")

        result = await tool.execute(csv_path="long.csv", tail_rows=5)
        assert "50 rows" in result
        assert "Last 5 rows" in result

    @pytest.mark.asyncio
    async def test_numeric_stats(self, tool, tmp_path: Path):
        csv = tmp_path / "stats.csv"
        csv.write_text("val\n10\n20\n30\n")

        result = await tool.execute(csv_path="stats.csv")
        assert "min=10" in result
        assert "max=30" in result
        assert "mean=20" in result
