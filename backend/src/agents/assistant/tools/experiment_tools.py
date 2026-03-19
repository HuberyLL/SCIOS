"""Experiment log parsing tools — summarise CSV training logs for the LLM."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from src.agents.assistant.tools.base import BaseTool
from src.agents.assistant.tools.fs_sandbox import resolve_and_check_path

logger = logging.getLogger(__name__)

_OUTPUT_CHAR_LIMIT = 3000


class ParseCSVLogArgs(BaseModel):
    csv_path: str = Field(..., description="Relative path (within workspace) to the CSV log file.")
    columns: list[str] = Field(
        default_factory=list,
        description="Columns to include in the output. Empty list means all columns.",
    )
    tail_rows: int = Field(
        10, ge=1, le=100,
        description="Number of rows from the end of the file to display.",
    )


class ParseCSVLogTool(BaseTool):
    name = "parse_csv_log"
    description = (
        "Parse a CSV experiment log file. Returns basic statistics (row/column counts, "
        "min/max/mean for numeric columns) and the last N rows so the LLM can quickly "
        "judge training convergence without reading the entire file."
    )
    args_schema = ParseCSVLogArgs

    async def execute(self, **kwargs: Any) -> str:
        csv_path: str = kwargs["csv_path"]
        columns: list[str] = kwargs.get("columns", [])
        tail_rows: int = kwargs.get("tail_rows", 10)

        try:
            import pandas as pd
        except ImportError:
            return (
                "Error: pandas is not installed. "
                "Run `pip install pandas` to enable CSV log parsing."
            )

        resolved = resolve_and_check_path(csv_path)
        if not resolved.exists():
            return f"Error: file not found — {csv_path}"

        try:
            df = pd.read_csv(resolved)
        except Exception as exc:
            return f"Error reading CSV: {exc}"

        if df.empty:
            return "The CSV file is empty (0 rows)."

        if columns:
            available = [c for c in columns if c in df.columns]
            missing = [c for c in columns if c not in df.columns]
            if missing:
                warning = f"Warning: columns not found and skipped: {missing}\n"
            else:
                warning = ""
            if not available:
                return warning + "Error: none of the requested columns exist in the CSV."
            df = df[available]
        else:
            warning = ""

        parts: list[str] = []
        if warning:
            parts.append(warning)

        parts.append(f"Shape: {df.shape[0]} rows x {df.shape[1]} columns")
        parts.append(f"Columns: {list(df.columns)}")

        numeric_cols = df.select_dtypes(include="number")
        if not numeric_cols.empty:
            stats_lines = ["Numeric column stats:"]
            for col in numeric_cols.columns:
                s = numeric_cols[col]
                stats_lines.append(
                    f"  {col}: min={s.min():.6g}, max={s.max():.6g}, mean={s.mean():.6g}"
                )
            parts.append("\n".join(stats_lines))

        tail = df.tail(tail_rows)
        parts.append(f"\nLast {len(tail)} rows:\n{tail.to_string(index=False)}")

        output = "\n".join(parts)
        if len(output) > _OUTPUT_CHAR_LIMIT:
            output = (
                f"[Output truncated to {_OUTPUT_CHAR_LIMIT} chars]\n"
                + output[-_OUTPUT_CHAR_LIMIT:]
            )
        return output
