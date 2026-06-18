"""Responses service — orchestrates LLM calls, tool execution, response persistence."""

from __future__ import annotations

import json
import time
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.response_domain import build_response_resource
from app.infrastructure.repositories import conversation_store as store
from app.application.tools.builtin_tools import get_default_tools
from app.application.llm import LLMProvider, get_provider
from app.application.learn.service import LearnService


class ResponsesService:
    """Core service for handling response creation and LLM orchestration."""

    def __init__(self, db: AsyncSession, settings: Settings):
        self._db = db
        self._settings = settings
        self._provider: LLMProvider | None = None

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = get_provider(self._settings)
        return self._provider

    def normalize_input(self, raw_input: str | list) -> list[dict]:
        """Normalize input to list-of-dicts format."""
        if isinstance(raw_input, str):
            return [{
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": raw_input}],
            }]
        # Already a list — convert pydantic models to dicts
        result = []
        for item in raw_input:
            if hasattr(item, "model_dump"):
                result.append(item.model_dump())
            elif isinstance(item, dict):
                result.append(item)
        return result

    def _build_system_prompt(self, instructions: str | None = None, learn_context: str = "") -> str:
        """Build system prompt with auto-fetched datasource metadata and learn context."""
        base = (
            "你是 ChatSQL 智能问数助手。用户会用自然语言提问，你需要：\n"
            "1. 理解用户意图，必要时调用 ask_clarification 澄清\n"
            "2. 使用 planning 工具输出分析规划\n"
            "3. 编写 SQL 查询数据（当前数据源支持标准 SQL）\n"
            "4. 用 smartbot_chart 工具返回图表结果\n"
            "5. 给出简洁的文字结论\n\n"
        )

        # Auto-fetch metadata from the active data source
        try:
            from app.application.datasources.manager import get_manager
            import asyncio as _aio
            mgr = get_manager()
            sources = mgr.list_sources()
            if sources:
                target = sources[0]["name"]
                loop = _aio.get_event_loop()
                if loop.is_running():
                    # Can't await in sync — use cached fallback
                    raise RuntimeError("skip")
                metadata = loop.run_until_complete(mgr.get_full_metadata(target))
                if metadata.get("tables"):
                    base += "可用的数据源表结构：\n"
                    for t in metadata["tables"]:
                        cols = ", ".join(
                            f"{c['name']}({c['type']})" if c.get("type") else c["name"]
                            for c in t.get("columns", [])
                        )
                        comment = f" — {t['comment']}" if t.get("comment") else ""
                        base += f"- {t['name']}({cols}){comment}\n"
                    base += "\n"
        except Exception:
            # Fallback to hardcoded demo schema
            base += (
                "可用的表：\n"
                "- orders(city, dt, gmv, order_count, avg_delay_days) — 订单数据\n"
                "- routes(route, capacity, actual, load_rate, dt) — 线路装载率\n"
                "- sort_center(center_name, volume) — 分拣中心货量\n"
            )

        if learn_context:
            base = f"{base}\n{learn_context}\n"
        if instructions:
            base = f"{base}\n{instructions}"
        return base

    def _get_tools(self, request_tools: list[dict] | None) -> list[dict]:
        """Return tools to send to LLM — default tools if not specified."""
        if request_tools is None:
            return get_default_tools()
        return request_tools

    def _extract_user_query(self, input_items: list[dict]) -> str:
        """Extract the latest user query from input items."""
        for item in reversed(input_items):
            if item.get("type") == "message" and item.get("role") == "user":
                content_parts = item.get("content", [])
                return " ".join(
                    p.get("text", "") for p in content_parts
                    if p.get("type") in ("input_text", "output_text")
                )
        return ""

    async def call_llm_stream(
        self,
        input_items: list[dict],
        model: str,
        instructions: str | None,
        tools: list[dict] | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Call LLM with streaming, yield chunks for SSE pipeline."""
        # Build learn context from user query
        user_query = self._extract_user_query(input_items)
        learn_context = ""
        if user_query:
            try:
                learn_service = LearnService(self._db, self._settings)
                learn_context = await learn_service.build_learn_context(user_query)
            except Exception as e:
                # Learn context is best-effort, don't block LLM call
                import logging
                logging.getLogger("chatsql").warning(f"Learn context build failed: {e}")

        # Build messages
        messages = [{"role": "system", "content": self._build_system_prompt(instructions, learn_context)}]
        for item in input_items:
            if item.get("type") == "message":
                role = item.get("role", "user")
                content_parts = item.get("content", [])
                text = " ".join(p.get("text", "") for p in content_parts if p.get("type") in ("input_text", "output_text"))
                if text:
                    messages.append({"role": role, "content": text})
            elif item.get("type") == "function_call_output":
                # Tool result — add as tool message
                messages.append({
                    "role": "tool",
                    "tool_call_id": item.get("call_id", ""),
                    "content": item.get("output", ""),
                })

        # Prepare tools
        llm_tools = self._get_tools(tools)

        # Call LLM via provider abstraction
        async for chunk in self.provider.stream_chat(
            messages=messages,
            tools=llm_tools,
            model=model,
            temperature=self._settings.llm_temperature,
            max_tokens=self._settings.llm_max_tokens,
        ):
            yield chunk

    async def run_completion(
        self,
        *,
        response_id: str,
        session_id: str,
        input_items: list[dict],
        model: str,
        instructions: str | None = None,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        """Non-streaming completion — run to completion and return ResponseResource."""
        output_items: list[dict] = []
        full_text = ""

        async for chunk in self.call_llm_stream(input_items, model, instructions, tools):
            if chunk["type"] == "text_delta":
                full_text += chunk["text"]
            elif chunk["type"] == "text_done":
                output_items.append({
                    "type": "message",
                    "id": f"msg_{response_id}",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": chunk["text"]}],
                    "status": "completed",
                })
            elif chunk["type"] == "function_call":
                output_items.append({
                    "type": "function_call",
                    "id": f"fc_{response_id}_{len(output_items)}",
                    "call_id": chunk["call_id"],
                    "name": chunk["name"],
                    "arguments": chunk["arguments"],
                    "status": "completed",
                })

        # Persist
        await store.complete_response(
            self._db,
            response_id,
            output_items=output_items,
            status="completed",
            model=model,
        )

        # Trigger learn extraction in background (non-blocking)
        import asyncio
        asyncio.create_task(
            self.trigger_learn_extraction(response_id, session_id, input_items, output_items)
        )

        return build_response_resource(
            response_id=response_id,
            model=model,
            output=output_items,
            status="completed",
        )

    async def complete_response(self, response_id: str, output_items: list[dict]) -> None:
        """Persist completed response to DB."""
        await store.complete_response(
            self._db,
            response_id,
            output_items=output_items,
            status="completed",
        )

    async def trigger_learn_extraction(
        self,
        response_id: str,
        session_id: str,
        input_items: list[dict],
        output_items: list[dict],
    ) -> None:
        """Background task: extract learnable routines from completed response."""
        try:
            user_query = self._extract_user_query(input_items)
            if not user_query:
                return

            # Extract assistant output text
            assistant_text = ""
            for item in output_items:
                if item.get("type") == "message" and item.get("role") == "assistant":
                    content_parts = item.get("content", [])
                    assistant_text += " ".join(
                        p.get("text", "") for p in content_parts
                        if p.get("type") in ("input_text", "output_text")
                    )
            if not assistant_text:
                return

            learn_service = LearnService(self._db, self._settings)
            await learn_service.extract_from_response(
                session_id=session_id,
                response_id=response_id,
                user_q=user_query,
                assistant_output=assistant_text,
            )
        except Exception as e:
            import logging
            logging.getLogger("chatsql").warning(f"Learn extraction failed: {e}")
