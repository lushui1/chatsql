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

    # 表结构注入的字符预算。超出预算说明数据源表太多，
    # 此时宁可少给几张表，也不要把整个库塞进 prompt —— 见下面的分层说明。
    SCHEMA_BUDGET = 4000

    async def _build_system_prompt(self, user_query: str = "", instructions: str | None = None, learn_context: str = "") -> str:
        """Build system prompt with auto-fetched datasource metadata and learn context.

        分层原则（源自 smartqa 五轮 prompt 迭代的实测结论）：
        - **必带层**：角色流程、SQL 规则。短，且不能删。
        - **按需层**：RAG 检索出的相关表 / 术语 / 示例。命中才注入。
        - **兜底层**：RAG 没命中时，才退化为全量表结构，且受字符预算约束。

        实测证据：prompt 从 5155 字符压到 2981 字符后准确率反而从 43% 升到 53%
        —— 指令越长，模型越容易漏掉其中某几条（指令稀释）。
        所以这里不做"能塞多少塞多少"，而是"相关才注入"。
        """
        from app.application.sql_validator import SQLValidator

        parts: list[str] = []

        # ── 第 1 层：角色与工具流程（必带，保持精简）──
        parts.append(
            "你是 ChatSQL 智能问数助手。流程：\n"
            "1. 意图不清时先用 ask_clarification 澄清，不要猜\n"
            "2. 复杂问题先用 planning 拆解，简单问题直接写 SQL\n"
            "3. 用 execute_sql 取真实数据 —— 绝对不要编造结果\n"
            "4. 用 chatsql_chart 展示，并给一句结论\n"
        )

        # ── 第 2 层：SQL 规则（必带，内容由校验器生成）──
        parts.append(SQLValidator.describe_rules())

        # ── 第 3 层：RAG 按需召回的业务上下文 ──
        rag_result: dict = {}
        if user_query:
            try:
                from app.application.rag_service import retrieve_context, build_context_prompt
                rag_result = await retrieve_context(user_query)
                rag_prompt = build_context_prompt(rag_result)
                if rag_prompt:
                    parts.append(rag_prompt)
            except Exception as e:
                logger.warning(f"RAG context retrieval failed: {e}")

        # ── 第 4 层：表结构。RAG 命中了相关表就优先用，否则兜底全量 ──
        schema_block = await self._build_schema_block(rag_result)
        if schema_block:
            parts.insert(2, schema_block)  # 表结构放在规则之后、业务上下文之前

        # ── 第 5 层：学习到的经验与调用方自定义指令 ──
        if learn_context:
            parts.append(learn_context)
        if instructions:
            parts.append(instructions)

        return "\n\n".join(p for p in parts if p)

    async def _build_schema_block(self, rag_result: dict) -> str:
        """Build the table-schema section of the prompt.

        两个信息源必须合并，缺一不可：

        - **数据源真实元数据**（`get_full_metadata`）：有字段名和类型，
          写 SQL 靠它。但表多时不能全塞。
        - **业务上下文库**（RAG 召回的 `bc_tables`）：有业务含义、分类、
          中文名，但**通常没有字段列表**。

        所以分工是：RAG 负责回答「哪些表相关」，真实元数据负责回答
        「这些表的字段是什么」。只取 RAG 的表会导致 LLM 拿到表名却没有
        字段，照样写不出 SQL。

        注：这里曾经有个 bug —— 在 async 函数里调 `loop.run_until_complete()`
        前判断 `loop.is_running()`，而运行中的 loop 恒为 True，于是直接
        `raise RuntimeError("skip")` 跳到 except 分支。结果是**真实数据源的
        表结构永远拉不到**，prompt 里恒为硬编码的 demo 三张表。
        正确写法就是直接 await。
        """
        real_tables = await self._fetch_real_tables()

        # RAG 召回的表名（可能带业务描述，也可能不存在于真实库中）
        rag_tables = [t for t in (rag_result.get("relevant_tables") or [])
                      if t.get("name")]
        rag_names = [t["name"] for t in rag_tables]

        if rag_names:
            # 优先用真实元数据里的同名字段，RAG 只提供业务补充说明
            chosen, missing = [], []
            for name in rag_names:
                if name in real_tables:
                    t = dict(real_tables[name])
                    rag_desc = next(
                        (r.get("description") or r.get("display_name")
                         for r in rag_tables if r["name"] == name),
                        "",
                    )
                    if rag_desc and not t.get("comment"):
                        t["comment"] = rag_desc
                    chosen.append(t)
                else:
                    missing.append(name)

            # RAG 提到但真实库没有的表：明确告知，避免模型去查不存在的表
            note = ""
            if missing:
                note = f"\n\n（注意：{', '.join(missing)} 仅存在于业务上下文，当前数据源中没有该表，不要查询它。）"

            if chosen:
                return "## 相关表结构\n\n" + "\n\n".join(
                    self._format_table(t) for t in chosen
                ) + note
            # RAG 全都没命中真实表 —— 退化为全量，不能让 prompt 没有字段
            logger.warning(
                f"RAG recalled tables {rag_names} but none exist in datasource; "
                f"falling back to full schema"
            )

        if not real_tables:
            return ""

        lines = ["## 可用表结构"]
        used = 0
        omitted = 0
        for t in real_tables.values():
            block = self._format_table(t)
            if used + len(block) > self.SCHEMA_BUDGET and used > 0:
                omitted += 1
                continue
            lines.append(block)
            used += len(block)

        if omitted:
            lines.append(
                f"\n（还有 {omitted} 张表因篇幅未列出。若上面的表无法回答，"
                f"先向用户确认要查哪张表，不要臆造字段。）"
            )
        return "\n\n".join(lines)

    @staticmethod
    async def _fetch_real_tables() -> dict[str, dict]:
        """Fetch real table schema from the active data source. {name: table}"""
        try:
            from app.application.datasources.manager import get_manager
            mgr = get_manager()
            sources = mgr.list_sources()
            if not sources:
                return {}
            metadata = await mgr.get_full_metadata(sources[0]["name"])
        except Exception as e:
            logger.warning(f"datasource metadata fetch failed: {e}")
            return {}
        return {t["name"]: t for t in (metadata.get("tables") or []) if t.get("name")}

    @staticmethod
    def _format_table(t: dict) -> str:
        """Format one table's schema into prompt text."""
        cols = ", ".join(
            f"{c['name']}({c['type']})" if c.get("type") else c["name"]
            for c in t.get("columns", [])
        )
        comment = f" — {t['comment']}" if t.get("comment") else ""
        return f"### {t.get('name', '')}{comment}\n字段: {cols}"

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

        # Add LIMIT if not present.
        # 旧实现用 `"LIMIT" not in sql.upper()`，两个漏判：
        #   1) 只有子查询有 LIMIT 时，外层不加 -> 可能拉回全表
        #   2) 字符串字面量里出现 "limit" 单词 -> 误判为已有 LIMIT
        # enforce_limit 只在括号深度 0 的位置找 LIMIT，且基于词法掩码。
        sql = validator.enforce_limit(sql, limit=limit)

        from app.application.datasources.query_guard import QueryTimeoutError

        try:
            result = await mgr.execute(datasource, sql)
            return {
                "columns": result.get("columns", []),
                "rows": result.get("rows", [])[:limit],
                "row_count": len(result.get("rows", [])),
                "truncated": result.get("truncated", False),
            }
        except QueryTimeoutError as e:
            # 超时要告诉模型怎么改，否则它会原样重试那条慢 SQL
            return {
                "error": f"{e}。请简化查询：加更严格的时间/维度过滤、"
                         f"减少 JOIN、先聚合再排序，或改用抽样/近似统计。",
                "columns": [], "rows": [], "row_count": 0,
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
