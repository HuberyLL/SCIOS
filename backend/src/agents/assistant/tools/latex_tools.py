"""LaTeX compilation tool — compile .tex files to PDF within the workspace sandbox."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.agents.assistant.tools.base import BaseTool
from src.agents.assistant.tools.fs_sandbox import get_workspace_dir, resolve_and_check_path

logger = logging.getLogger(__name__)

_LOG_TAIL_CHARS = 1000
_PDFLATEX_TIMEOUT = 60


class CompileLatexArgs(BaseModel):
    tex_file_path: str = Field(
        ...,
        description="Relative path (within workspace) to the .tex file to compile.",
    )


class CompileLatexTool(BaseTool):
    name = "compile_latex"
    description = (
        "Compile a LaTeX (.tex) file to PDF using pdflatex. "
        "Runs twice to resolve cross-references. Returns the PDF path on success "
        "or the compilation error log on failure."
    )
    args_schema = CompileLatexArgs

    async def execute(self, **kwargs: Any) -> str:
        tex_file_path: str = kwargs["tex_file_path"]

        resolved = resolve_and_check_path(tex_file_path)
        if not resolved.exists():
            return f"Error: file not found — {tex_file_path}"
        if resolved.suffix.lower() != ".tex":
            return f"Error: expected a .tex file, got '{resolved.suffix}'"

        work_dir = resolved.parent
        filename = resolved.name

        try:
            for pass_num in (1, 2):
                proc = await asyncio.create_subprocess_exec(
                    "pdflatex", "-interaction=nonstopmode", filename,
                    cwd=str(work_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout=_PDFLATEX_TIMEOUT)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    return f"Error: pdflatex timed out on pass {pass_num} (>{_PDFLATEX_TIMEOUT}s)."
        except FileNotFoundError:
            return (
                "Error: pdflatex is not installed in the local environment. "
                "Please install a TeX distribution (e.g. TeX Live) first."
            )

        pdf_path = resolved.with_suffix(".pdf")
        if pdf_path.exists():
            workspace = get_workspace_dir()
            relative_pdf = pdf_path.relative_to(workspace)
            return f"Success. PDF generated at {relative_pdf}"

        log_path = resolved.with_suffix(".log")
        if log_path.exists():
            log_text = log_path.read_text(errors="replace")
            tail = log_text[-_LOG_TAIL_CHARS:] if len(log_text) > _LOG_TAIL_CHARS else log_text
            return f"Error: pdflatex compilation failed.\n--- log (last {_LOG_TAIL_CHARS} chars) ---\n{tail}"

        return "Error: pdflatex finished but no PDF or log file was produced."
