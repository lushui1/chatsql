"""Responses service — orchestrates LLM calls, tool execution, response persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.response_domain import build_response_resource
from app.infrastructure.repositories import conversation_store as store
from app.application.tools.builtin_tools import get_default_tools
from app.application.llm import LLMProvider, get_provider
from app.application.learn.service import LearnService

logger = logging.getLogger("chatsql")


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
        result = []
        for item in raw_input:
            if hasattr(item, "model_dump"):
                result.append(item.model_dump())
            elif isinstance(item, dict):
                result.append(item)
        return result

    async def _build_system_prompt(self, user_query: str = "", instructions: str | None = None, learn_context: str = "") -> str:
        """Build system prompt with auto-fetched datasource metadata and learn context."""
        base = (
            "你是 ChatSQL 智能问数助手。用户会用自然语言提问，你需要：\n"
            "1. 理解用户意图，必要时调用 ask_clarification 澄清\n"
            "2. 简单问题可直接写 SQL 查询；复杂问题先用 planning 工具输出分析规划\n"
            "3. 用 execute_sql 工具执行 SQL 获取真实数据（不要编造数据！）\n"
            "4. 用 smartbot_chart 工具将查询结果以图表/表格形式展示\n"
            "5. 给出简洁的文字结论\n\n"
            "⚠️ 重要：必须通过 execute_sql 获取真实数据，绝对不要猜测或编造查询结果。\n\n"
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
                    raise RuntimeError("skip")
                metadata = loop.run_until_complete(mgr.get_full_metadata(target))
                if metadata.get("tables"):
                    base += "## 可用数据源表结构\n\n"
                    for t in metadata["tables"]:
                        cols = ", ".join(
                            f"{c['name']}({c['type']})" if c.get("type") else c["name"]
                            for c in t.get("columns", [])
                        )
                        comment = f" — {t['comment']}" if t.get("comment") else ""
                        base += f"### {t['name']}{comment}\n字段: {cols}\n\n"
        except Exception:
            base += (
                "## 可用数据源表结构\n\n"
                "### orders — 物流订单\n"
                "字段: order_id(订单号), status(状态), create_time(创建时间), sort_center(分拣中心), amount(金额)\n\n"
                "### routes — 运输路线\n"
                "字段: route(路线), capacity(容量), actual(实际), load_rate(装载率), dt(日期)\n\n"
                "### sort_center — 分拣中心\n"
                "字段: center_name(中心名称), volume(货量)\n\n"
            )

        # RAG: inject business context
        if user_query:
            try:
                from app.application.rag_service import retrieve_context, build_context_prompt
                rag_result = await retrieve_context(user_query)
                rag_prompt = build_context_prompt(rag_result)
                if rag_prompt:
                    base += f"{rag_prompt}\n"
            except Exception as e:
                logger.warning(f"RAG context retrieval failed: {e}")

        # SQL safety rules
        base += (
            "## SQL 安全规则\n"
            "- 只允许 SELECT 查询，禁止 INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE\n"
            "- 禁止执行多条 SQL 语句\n"
            "- 子查询嵌套不超过 3 层\n\n"
        )

        if learn_context:
            base += f"{learn_context}\n"
        if instructions:
            base += f"{instructions}\n"
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

    async def _execute_sql(self, sql: str, datasource: str | None = None, limit: int = 1000) -> dict:
        """Execute SQL against a data source and return results."""
        # SQL safety validation
        from app.application.sql_validator import SQLValidator
        validator = SQLValidator()
        is_safe, reason = validator.validate(sql)
        if not is_safe:
            return {"error": f"SQL 安全校验不通过: {reason}", "columns": [], "rows": [], "row_count": 0}

        from app.application.datasources.manager import get_manager
        mgr = get_manager()

        if not datasource:
            sources = mgr.list_sources()
            if not sources:
                return {"error": "没有配置数据源", "columns": [], "rows": [], "row_count": 0}
            datasource = sources[0]["name"]

        # Add LIMIT if not present
        sql_stripped = sql.strip().rstrip(";").upper()
        if "LIMIT" not in sql_stripped:
            sql = sql.strip().rstrip(";") + f" LIMIT {limit}"

        try:
            result = await mgr.execute(datasource, sql)
            return {
                "columns": result.get("columns", []),
                "rows": result.get("rows", [])[:limit],
                "row_count": len(result.get("rows", [])),
            }
        except Exception as e:
            return {"error": str(e), "columns": [], "rows": [], "row_count": 0}

    async def call_llm_stream(
        self,
        input_items: list[dict],
        model: str,
        instructions: str | None,
        tools: list[dict] | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Call LLM with multi-turn tool execution loop, yield chunks for SSE.

        Flow:
        1. Call LLM with user message + tools
        2. If LLM returns function_call (e.g. execute_sql):
           - Execute the tool
           - Feed result back to LLM
           - Repeat until LLM produces final text (no more tool calls)
        3. Yield all chunks for SSE streaming
        """
        user_query = self._extract_user_query(input_items)
        learn_context = ""
        if user_query:
            try:
                learn_service = LearnService(self._db, self._settings)
                learn_context = await learn_service.build_learn_context(user_query)
            except Exception as e:
                logger.warning(f"Learn context build failed: {e}")

        # Build initial messages
        system_prompt = await self._build_system_prompt(user_query, instructions, learn_context)
        messages = [{"role": "system", "content": system_prompt}]
        for item in input_items:
            if item.get("type") == "message":
                role = item.get("role", "user")
                content_parts = item.get("content", [])
                text = " ".join(p.get("text", "") for p in content_parts if p.get("type") in ("input_text", "output_text"))
                if text:
                    messages.append({"role": role, "content": text})
            elif item.get("type") == "function_call_output":
                messages.append({
                    "role": "tool",
                    "tool_call_id": item.get("call_id", ""),
                    "content": item.get("output", ""),
                })

        llm_tools = self._get_tools(tools)
        MAX_TOOL_ROUNDS = 10  # Safety limit

        for round_num in range(MAX_TOOL_ROUNDS):
            # Call LLM
            collected_text = ""
            tool_calls: list[dict] = []  # {id, name, arguments}

            async for chunk in self.provider.stream_chat(
                messages=messages,
                tools=llm_tools,
                model=model,
                temperature=self._settings.llm_temperature,
                max_tokens=self._settings.llm_max_tokens,
            ):
                if chunk["type"] == "text_delta":
                    collected_text += chunk["text"]
                    yield chunk
                elif chunk["type"] == "function_call":
                    tool_calls.append({
                        "id": chunk.get("call_id", f"call_{round_num}_{len(tool_calls)}"),
                        "name": chunk.get("name", ""),
                        "arguments": chunk.get("arguments", ""),
                    })
                    yield chunk
                elif chunk["type"] == "text_done":
                    yield chunk

            # If no tool calls, we're done
            if not tool_calls:
                break

            # Check if there are execute_sql calls that need execution
            has_sql_calls = any(tc["name"] == "execute_sql" for tc in tool_calls)
            if not has_sql_calls:
                # No SQL to execute — tool calls are presentation-only (planning, chart, etc.)
                # These are already yielded to frontend, no need to feed back to LLM
                break

            # Execute SQL tools and build tool result messages
            assistant_message = {
                "role": "assistant",
                "content": collected_text or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in tool_calls
                ],
            }
            messages.append(assistant_message)

            for tc in tool_calls:
                if tc["name"] == "execute_sql":
                    try:
                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}

                    sql = args.get("sql", "")
                    datasource = args.get("datasource")
                    limit = args.get("limit", 1000)

                    logger.info(f"Executing SQL: {sql[:200]}")
                    result = await self._execute_sql(sql, datasource, limit)

                    result_str = json.dumps(result, ensure_ascii=False, default=str)
                    # Truncate if too large
                    if len(result_str) > 50000:
                        result_str = result_str[:50000] + "\n... (结果过大已截断)"

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_str,
                    })

                    # Yield execution result for frontend
                    yield {
                        "type": "tool_result",
                        "call_id": tc["id"],
                        "name": "execute_sql",
                        "result": result,
                    }
                else:
                    # Non-SQL tool calls — pass through as-is
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": "ok",
                    })

            # Continue loop — LLM will be called again with tool results

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

        await store.complete_response(
            self._db,
            response_id,
            output_items=output_items,
            status="completed",
            model=model,
        )

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
            logger.warning(f"Learn extraction failed: {e}")
