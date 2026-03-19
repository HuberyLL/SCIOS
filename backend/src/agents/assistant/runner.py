"""AssistantRunner — the core Agent Loop that drives function-calling
conversations between the user, the LLM and registered tools."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import litellm
import tiktoken
from pydantic import ValidationError
from sqlmodel import Session, select

from src.agents.assistant.tools.registry import ToolRegistry
from src.core.config import get_settings
from src.models.assistant import AssistantMessage, AssistantSession, Memory, MessageRole
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
        self.model = cfg.assistant_model or cfg.llm_model
        self.api_base = cfg.llm_base_url or None
        self.api_key = cfg.llm_api_key or None
        self.max_rounds = cfg.assistant_max_tool_rounds
        self.max_context_tokens = cfg.assistant_max_context_tokens
        self.max_memory_items = cfg.assistant_memory_max_items
        self.max_memory_tokens = cfg.assistant_memory_max_tokens
        self.system_prompt = cfg.assistant_system_prompt or DEFAULT_SYSTEM_PROMPT

        try:
            self._encoder = tiktoken.encoding_for_model(self.model)
        except KeyError:
            self._encoder = tiktoken.get_encoding("cl100k_base")

    # ------------------------------------------------------------------
    # Long-term memory
    # ------------------------------------------------------------------

    def _load_memories(self) -> list[Memory]:
        """Return all persisted memory facts, ordered by creation time."""
        with Session(get_engine()) as db:
            stmt = select(Memory).order_by(Memory.created_at)  # type: ignore[arg-type]
            return list(db.exec(stmt).all())

    def _build_system_prompt(self) -> str:
        """Return the system prompt with long-term memories appended."""
        memories = self._load_memories()
        if not memories:
            return self.system_prompt

        # Keep memory prompt bounded to avoid consuming the full context window.
        head = "\n\n## Known facts about the user (long-term memory):\n"
        tail = "\n\nUse the update_memory tool to add new facts or delete outdated ones."
        head_tokens = self._count_tokens(head)
        tail_tokens = self._count_tokens(tail)
        available_tokens = max(0, self.max_memory_tokens - head_tokens - tail_tokens)

        selected: list[str] = []
        used_tokens = 0
        omitted = 0

        # Prefer more recent memories first.
        for m in reversed(memories):
            if len(selected) >= self.max_memory_items:
                omitted += 1
                continue
            line = f"- [id:{m.id[:8]}] ({m.category}) {m.content}"
            line_tokens = self._count_tokens(line + "\n")
            if used_tokens + line_tokens > available_tokens:
                omitted += 1
                continue
            selected.append(line)
            used_tokens += line_tokens

        selected.reverse()
        if omitted > 0:
            selected.append(f"- ... ({omitted} older memory items omitted)")

        if not selected:
            return self.system_prompt

        memory_block = head + "\n".join(selected) + tail
        return self.system_prompt + memory_block

    # ------------------------------------------------------------------
    # Token counting & context trimming
    # ------------------------------------------------------------------

    def _count_tokens(self, text: str) -> int:
        """Count tokens using the tiktoken encoder for the current model."""
        return len(self._encoder.encode(text))

    def _count_msg_tokens(self, msg: dict[str, Any]) -> int:
        """Estimate the token cost of a single OpenAI message dict."""
        tokens = self._count_tokens(msg.get("content") or "")
        if msg.get("tool_calls"):
            tokens += self._count_tokens(
                json.dumps(msg["tool_calls"], ensure_ascii=False)
            )
        tokens += 4  # per-message overhead (role, separators)
        return tokens

    @staticmethod
    def _segment_history(history: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Split the flat message list into atomic groups.

        An assistant message with ``tool_calls`` and its subsequent tool
        responses form a single indivisible group.  Every other message is
        its own group.
        """
        groups: list[list[dict[str, Any]]] = []
        i = 0
        while i < len(history):
            msg = history[i]
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                group = [msg]
                i += 1
                while i < len(history) and history[i]["role"] == "tool":
                    group.append(history[i])
                    i += 1
                groups.append(group)
            else:
                groups.append([msg])
                i += 1
        return groups

    def _truncate_text_to_tokens(self, text: str, max_tokens: int) -> str:
        """Return text truncated to at most ``max_tokens`` tokens."""
        if max_tokens <= 0 or not text:
            return ""
        ids = self._encoder.encode(text)
        if len(ids) <= max_tokens:
            return text
        truncated = self._encoder.decode(ids[:max_tokens]).rstrip()
        return truncated or ""

    def _force_fit_group(
        self, group: list[dict[str, Any]], remaining_budget: int
    ) -> list[dict[str, Any]] | None:
        """Try to force-fit the newest group into remaining budget.

        Only supports a single non-tool message by truncating its content.
        Tool-call groups remain atomic and are not partially trimmed.
        """
        if remaining_budget <= 0 or len(group) != 1:
            return None

        msg = group[0]
        if msg.get("role") == "tool" or msg.get("tool_calls"):
            return None

        base_overhead = 4
        available_for_content = remaining_budget - base_overhead
        if available_for_content <= 0:
            return None

        original = msg.get("content") or ""
        truncated = self._truncate_text_to_tokens(original, available_for_content)
        if not truncated and original:
            return None

        forced = dict(msg)
        forced["content"] = truncated
        return [forced]

    def _trim_history(
        self, system_prompt_text: str, history: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Keep the most recent message groups that fit within the token budget.

        The *system prompt* (which already includes long-term memories) is
        protected and always sent — its token cost is subtracted from the
        total budget first.
        """
        system_tokens = self._count_msg_tokens(
            {"role": "system", "content": system_prompt_text}
        )
        budget = self.max_context_tokens - system_tokens
        if budget <= 0:
            return []

        groups = self._segment_history(history)

        kept: list[list[dict[str, Any]]] = []
        used = 0
        for idx, group in enumerate(reversed(groups)):
            is_newest_group = idx == 0
            group_tokens = sum(self._count_msg_tokens(m) for m in group)
            if used + group_tokens > budget:
                if is_newest_group:
                    forced = self._force_fit_group(group, budget - used)
                    if forced:
                        kept.append(forced)
                break
            kept.append(group)
            used += group_tokens

        kept.reverse()
        return [msg for group in kept for msg in group]

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

        system_content = self._build_system_prompt()
        history = self._load_history()
        trimmed = self._trim_history(system_content, history)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_content}
        ]
        messages.extend(trimmed)

        tool_defs = ToolRegistry.get_all_tools_for_llm()

        for _round in range(self.max_rounds):
            try:
                stream = await litellm.acompletion(
                    model=self.model,
                    messages=messages,
                    tools=tool_defs or None,
                    stream=True,
                    api_base=self.api_base,
                    api_key=self.api_key,
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
