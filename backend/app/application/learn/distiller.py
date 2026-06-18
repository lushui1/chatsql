"""ResponseDistiller — 从对话响应中提炼学习材料。

调用 LLM 判断是否值得学习，并提取结构化套路。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import Settings
from app.application.llm import get_provider

logger = logging.getLogger("chatsql.learn")


# ── Prompts ──

SHOULD_LEARN_PROMPT = """你是一个学习分析器。判断以下用户问题和助手回答是否包含可复用的分析模式。

判断标准：
- 包含 SQL 查询 → 值得学
- 多步骤分析流程 → 值得学
- 有明确业务结论 → 值得学
- 闲聊/简单问候/一次性简单查询 → 不值得学
- 纯粹介绍性/解释性回答 → 不值得学

用户问题：
{question}

助手回答：
{answer}

严格返回 JSON 格式，不要返回其他内容：
{{"should_learn": true/false, "reason": "简短理由"}}"""

EXTRACT_ROUTINE_PROMPT = """你是一个知识提取器。从以下对话中提取可复用的分析套路。

用户问题：
{question}

助手回答：
{answer}

提取要求：
1. 如果包含 SQL，提取 SQL 模板（用 {{param}} 标记可变参数），并说明适用场景
2. 如果是多步骤分析，提取分析框架和步骤
3. 如果有业务规则，提取规则描述

严格返回 JSON 格式，不要返回其他内容：
{{
  "title": "套路标题（简短）",
  "summary": "一句话总结",
  "routine_type": "sql_routine | analysis_framework | business_rule",
  "content": "完整套路内容（SQL模板+说明，或分析步骤等）",
  "tags": ["标签1", "标签2"]
}}"""


class ResponseDistiller:
    """从对话响应中提炼学习材料。"""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._provider = None

    @property
    def provider(self):
        if self._provider is None:
            self._provider = get_provider(self._settings)
        return self._provider

    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM 获取纯文本响应。"""
        messages = [{"role": "user", "content": prompt}]
        full_text = ""
        async for chunk in self.provider.stream_chat(
            messages=messages,
            tools=None,
            model=self._settings.llm_model,
            temperature=0.1,
            max_tokens=1024,
        ):
            if chunk["type"] == "text_delta":
                full_text += chunk["text"]
        return full_text.strip()

    async def should_learn(self, user_question: str, assistant_output: str) -> bool:
        """判断这次回答是否值得学习。"""
        try:
            prompt = SHOULD_LEARN_PROMPT.format(
                question=user_question[:1000],
                answer=assistant_output[:2000],
            )
            raw = await self._call_llm(prompt)
            # 尝试解析 JSON（兼容 markdown code block）
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)
            should = result.get("should_learn", False)
            reason = result.get("reason", "")
            logger.debug(f"should_learn={should}, reason={reason}")
            return bool(should)
        except Exception as e:
            logger.warning(f"should_learn 判断失败: {e}")
            return False

    async def extract_routine(self, user_question: str, assistant_output: str) -> dict[str, Any] | None:
        """提取套路内容。返回 {title, summary, routine_type, content, tags} 或 None。"""
        try:
            prompt = EXTRACT_ROUTINE_PROMPT.format(
                question=user_question[:1000],
                answer=assistant_output[:2000],
            )
            raw = await self._call_llm(prompt)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)

            # 验证必要字段
            required = ["title", "summary", "routine_type", "content"]
            if not all(k in result for k in required):
                logger.warning(f"提取结果缺少必要字段: {result.keys()}")
                return None

            # 确保 tags 是列表
            if not isinstance(result.get("tags"), list):
                result["tags"] = []

            return result
        except Exception as e:
            logger.warning(f"extract_routine 提取失败: {e}")
            return None
