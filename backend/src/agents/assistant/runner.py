"""AssistantRunner — the core Agent Loop that drives function-calling
conversations between the user, the LLM and registered tools."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError
from sqlmodel import Session, select

from src.agents.assistant.tools.registry import ToolRegistry
from src.core.config import get_settings
from src.models.assistant import AssistantMessage, AssistantSession, MessageRole
from src.models.db import get_engine

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are SCIOS, an advanced AI academic research and coding assistant.\n"
    "You have access to a local sandbox workspace and a suite of powerful tools, including file operations, a persistent bash shell, python REPL, LaTeX compilation, and academic literature search.\n\n"
    "CRITICAL INSTRUCTIONS:\n"
    "1. ACT IN THE WORKSPACE: Never just output code, LaTeX, or scripts as plain text in your chat response if the user asks you to write or modify a document. Instead, directly use `write_file` or `edit_file` to create or modify files in the workspace.\n"
    "2. BUILD AND VERIFY: If you write or modify a LaTeX document (.tex), you MUST immediately compile it using the `compile_latex` tool or `bash_command`. If compilation fails, analyze the logs, fix the errors using `edit_file`, and recompile until successful.\n"
    "3. EXPLORE BEFORE EDITING: If asked to modify an existing project, use `bash_command` (e.g., `ls -la`, `grep`) or `read_file` to understand the directory structure and file contents before making changes.\n"
    "4. MULTI-STEP REASONING: Complex tasks (like writing a paper section) require multiple steps. Chain your tool calls logically: Search literature -> Read abstracts -> Modify .tex file -> Compile -> Fix errors.\n"
    "5. CONCISE COMMUNICATION: Briefly state what you are doing. Avoid dumping large file contents or long compilation logs in the chat. The user can see the files in the workspace."
)


class AssistantRunner:
    """Drives a single chat turn inside an assistant session.

    Instantiate with a ``session_id``, then iterate over
    :meth:`stream_chat` to get real-time events (text deltas, tool calls,
    etc.) that should be forwarded to the client over WebSocket.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        cfg = get_settings()
        self.client = AsyncOpenAI(
            base_url=cfg.llm_base_url,
            api_key=cfg.llm_api_key,
        )
        self.model = cfg.assistant_model or cfg.llm_model
        self.max_rounds = cfg.assistant_max_tool_rounds
        self.system_prompt = cfg.assistant_system_prompt or DEFAULT_SYSTEM_PROMPT

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def _load_history(self) -> list[dict[str, Any]]:
        """Load all persisted messages for this session and convert them to
        the OpenAI ``messages`` list format."""
        with Session(get_engine()) as db:
            stmt = (
                select(AssistantMessage)
                .where(AssistantMessage.session_id == self.session_id)
                .order_by(AssistantMessage.created_at)  # type: ignore[arg-type]
            )
            rows = db.exec(stmt).all()

        messages: list[dict[str, Any]] = []
        for row in rows:
            msg: dict[str, Any] = {"role": row.role.value, "content": row.content or ""}
            if row.role == MessageRole.assistant and row.tool_calls:
                msg["tool_calls"] = row.tool_calls
                if not msg["content"]:
                    msg["content"] = None
            if row.role == MessageRole.tool and row.tool_call_id:
                msg["tool_call_id"] = row.tool_call_id
            messages.append(msg)
        return messages

    def _save_message(
        self,
        role: MessageRole,
        content: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
    ) -> AssistantMessage:
        msg = AssistantMessage(
            session_id=self.session_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
        )
        with Session(get_engine()) as db:
            db.add(msg)
            session = db.get(AssistantSession, self.session_id)
            if session is not None:
                session.updated_at = datetime.now(timezone.utc)
                db.add(session)
            db.commit()
            db.refresh(msg)
        return msg

    @staticmethod
    def _suggest_title_from_user_input(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return "New Chat"
        if len(cleaned) > 40:
            return f"{cleaned[:37].rstrip()}..."
        return cleaned

    def _maybe_auto_set_session_title(self, user_input: str) -> None:
        with Session(get_engine()) as db:
            session = db.get(AssistantSession, self.session_id)
            if session is None:
                return
            if session.title and session.title != "New Chat":
                return

            user_rows = db.exec(
                select(AssistantMessage.id).where(
                    AssistantMessage.session_id == self.session_id,
                    AssistantMessage.role == MessageRole.user,
                )
            ).first()
            if user_rows is not None:
                return

            session.title = self._suggest_title_from_user_input(user_input)
            session.updated_at = datetime.now(timezone.utc)
            db.add(session)
            db.commit()

    # ------------------------------------------------------------------
    # Core Agent Loop
    # ------------------------------------------------------------------

    async def stream_chat(self, user_input: str) -> AsyncGenerator[dict[str, Any], None]:
        """Async generator that yields real-time events for a single user
        turn.  The loop calls the LLM, handles tool calls, and repeats
        until the LLM produces a final text reply or the round limit is
        reached."""

        self._maybe_auto_set_session_title(user_input)
        self._save_message(MessageRole.user, content=user_input)

        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self._load_history())

        tool_defs = ToolRegistry.get_all_tools_for_llm()

        for _round in range(self.max_rounds):
            try:
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tool_defs or None,
                    stream=True,
                )
            except Exception as exc:
                logger.exception("LLM call failed")
                yield {"event": "error", "data": {"message": str(exc)}}
                return

            # Accumulators for this streaming response
            full_content = ""
            tool_calls_buf: dict[int, dict[str, Any]] = {}
            finish_reason: str | None = None

            try:
                async for chunk in stream:
                    choice = chunk.choices[0] if chunk.choices else None
                    if choice is None:
                        continue
                    delta = choice.delta
                    finish_reason = choice.finish_reason or finish_reason

                    # --- Text delta ---
                    if delta.content:
                        full_content += delta.content
                        yield {
                            "event": "text_delta",
                            "data": {"content": delta.content},
                        }

                    # --- Tool-call delta (incremental assembly) ---
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_calls_buf:
                                tool_calls_buf[idx] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            buf = tool_calls_buf[idx]
                            if tc_delta.id:
                                buf["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    buf["function"]["name"] += tc_delta.function.name
                                if tc_delta.function.arguments:
                                    buf["function"]["arguments"] += tc_delta.function.arguments
            except Exception as exc:
                logger.exception("Error while streaming LLM response")
                yield {"event": "error", "data": {"message": str(exc)}}
                return

            # --- Decide what to do after the stream ends ---
            collected_tool_calls = [tool_calls_buf[i] for i in sorted(tool_calls_buf)]

            if finish_reason == "tool_calls" or collected_tool_calls:
                # LLM wants to call tools
                self._save_message(
                    MessageRole.assistant,
                    content=full_content,
                    tool_calls=collected_tool_calls,
                )
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": full_content or None,
                    "tool_calls": collected_tool_calls,
                }
                messages.append(assistant_msg)

                # Execute each tool call
                for tc in collected_tool_calls:
                    fn_name = tc["function"]["name"]
                    raw_args = tc["function"]["arguments"]
                    tc_id = tc["id"]
                    parsed_args: dict[str, Any] = {}
                    parse_error: str | None = None

                    if raw_args:
                        try:
                            parsed_json = json.loads(raw_args)
                            if not isinstance(parsed_json, dict):
                                raise ValueError(
                                    f"tool arguments must be a JSON object, got {type(parsed_json).__name__}"
                                )
                            parsed_args = parsed_json
                        except (json.JSONDecodeError, ValueError) as exc:
                            parse_error = f"Error: invalid JSON arguments for tool '{fn_name}': {exc}"
                            logger.warning(
                                "Invalid tool arguments JSON for tool=%s tool_call_id=%s: %s",
                                fn_name,
                                tc_id,
                                raw_args,
                            )

                    yield {
                        "event": "tool_call_start",
                        "data": {
                            "tool_name": fn_name,
                            "tool_call_id": tc_id,
                            "tool_args": parsed_args if parse_error is None else {},
                        },
                    }

                    tool = ToolRegistry.get(fn_name)
                    if tool is None:
                        result_str = f"Error: unknown tool '{fn_name}'"
                    elif parse_error is not None:
                        result_str = parse_error
                    else:
                        try:
                            validated_args = tool.args_schema.model_validate(parsed_args)
                            result = await tool.execute(**validated_args.model_dump())
                            result_str = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
                        except ValidationError as exc:
                            logger.warning(
                                "Tool %s validation failed for tool_call_id=%s: %s",
                                fn_name,
                                tc_id,
                                exc,
                            )
                            result_str = f"Error: invalid arguments for tool '{fn_name}': {exc}"
                        except Exception as exc:
                            logger.exception("Tool %s execution failed", fn_name)
                            result_str = f"Error executing tool: {exc}"

                    yield {
                        "event": "tool_call_result",
                        "data": {"tool_name": fn_name, "tool_call_id": tc_id, "result": result_str},
                    }

                    self._save_message(
                        MessageRole.tool,
                        content=result_str,
                        tool_call_id=tc_id,
                    )
                    messages.append(
                        {"role": "tool", "content": result_str, "tool_call_id": tc_id}
                    )

                # Loop back to call LLM again with tool results
                continue

            # No tool calls — final text reply
            self._save_message(MessageRole.assistant, content=full_content)
            yield {
                "event": "message_complete",
                "data": {"content": full_content},
            }
            return

        # Exhausted max rounds
        yield {
            "event": "error",
            "data": {"message": f"Agent loop exceeded {self.max_rounds} tool rounds"},
        }
