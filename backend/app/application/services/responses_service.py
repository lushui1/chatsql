"""Responses service — orchestrates LLM calls, tool execution, response persistence."""

from __future__ import annotations

import json
import time
from typing import Any, AsyncGenerator

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.response_domain import build_response_resource
from app.infrastructure.repositories import conversation_store as store
from app.application.tools.builtin_tools import get_default_tools


class ResponsesService:
    """Core service for handling response creation and LLM orchestration."""

    def __init__(self, db: AsyncSession, settings: Settings):
        self._db = db
        self._settings = settings
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._settings.llm_api_key or "dummy",
                base_url=self._settings.llm_base_url,
            )
        return self._client

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

    def _build_system_prompt(self, instructions: str | None = None) -> str:
        """Build system prompt with datasource context."""
        base = (
            "你是 ChatSQL 智能问数助手。用户会用自然语言提问，你需要：\n"
            "1. 理解用户意图，必要时调用 ask_clarification 澄清\n"
            "2. 使用 planning 工具输出分析规划\n"
            "3. 编写 SQL 查询数据（当前数据源支持标准 SQL）\n"
            "4. 用 smartbot_chart 工具返回图表结果\n"
            "5. 给出简洁的文字结论\n\n"
            "可用的表：\n"
            "- orders(city, dt, gmv, order_count, avg_delay_days) — 订单数据\n"
            "- routes(route, capacity, actual, load_rate, dt) — 线路装载率\n"
            "- sort_center(center_name, volume) — 分拣中心货量\n"
        )
        if instructions:
            base = f"{base}\n{instructions}"
        return base

    def _get_tools(self, request_tools: list[dict] | None) -> list[dict]:
        """Return tools to send to LLM — default tools if not specified."""
        if request_tools is None:
            return get_default_tools()
        return request_tools

    async def call_llm_stream(
        self,
        input_items: list[dict],
        model: str,
        instructions: str | None,
        tools: list[dict] | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Call LLM with streaming, yield chunks for SSE pipeline."""
        # Build messages
        messages = [{"role": "system", "content": self._build_system_prompt(instructions)}]
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

        # Prepare tools for OpenAI format
        llm_tools = self._get_tools(tools)
        openai_tools = [{"type": "function", "function": {k: v for k, v in t.items() if k != "type"}} for t in llm_tools]

        # Call LLM
        stream = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            tools=openai_tools if openai_tools else None,
            stream=True,
            temperature=0.3,
        )

        current_tool_call: dict | None = None
        full_text = ""

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # Text content
            if delta.content:
                full_text += delta.content
                yield {"type": "text_delta", "text": delta.content}

            # Tool calls
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    if tc.id:  # New tool call starts
                        if current_tool_call:
                            # Finish previous
                            yield {
                                "type": "function_call",
                                "call_id": current_tool_call["call_id"],
                                "name": current_tool_call["name"],
                                "arguments": current_tool_call["arguments"],
                            }
                        current_tool_call = {
                            "call_id": tc.id,
                            "name": tc.function.name if tc.function else "",
                            "arguments": "",
                        }
                    if tc.function and tc.function.arguments:
                        if current_tool_call:
                            current_tool_call["arguments"] += tc.function.arguments

        # Text done
        if full_text:
            yield {"type": "text_done", "text": full_text}

        # Finish pending tool call
        if current_tool_call:
            yield {
                "type": "function_call",
                "call_id": current_tool_call["call_id"],
                "name": current_tool_call["name"],
                "arguments": current_tool_call["arguments"],
            }

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
