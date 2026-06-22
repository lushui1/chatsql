"""Built-in Function Tools — execute_sql, planning, chart, clarification, subscription."""

from __future__ import annotations

from typing import Any


# Tool definitions (OpenAI function format)
DEFAULT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "execute_sql",
        "description": (
            "执行 SQL 查询并返回结果数据。这是获取真实数据的唯一方式。\n"
            "必须先用本工具查询数据，再用 smartbot_chart 展示图表。\n"
            "返回格式: {columns: [{name, type}], rows: [dict], row_count: int}"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "要执行的 SQL 语句",
                },
                "datasource": {
                    "type": "string",
                    "description": "数据源名称（可选，默认使用当前数据源）",
                },
                "limit": {
                    "type": "integer",
                    "description": "限制返回行数（默认 1000）",
                },
            },
            "required": ["sql"],
        },
    },
    {
        "type": "function",
        "name": "planning",
        "description": (
            "输出分析规划：整体解题思路(overview)、步骤列表(steps)、每步用到的表及选表理由。"
            "用户问题需多步分析或访问数据源时，应先调用本工具输出规划。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "overview": {
                    "type": "string",
                    "description": "整体解题思路/推理摘要",
                },
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "title": {"type": "string"},
                            "details": {
                                "type": "object",
                                "properties": {
                                    "reasoning": {"type": "string"},
                                    "dataSources": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "name": {"type": "string"},
                                                "reason": {"type": "string"},
                                            },
                                        },
                                    },
                                },
                            },
                        },
                        "required": ["id", "title", "details"],
                    },
                },
            },
            "required": ["steps"],
        },
    },
    {
        "type": "function",
        "name": "smartbot_chart",
        "description": "生成图表数据（柱状图、条形图、折线图、饼图、表格）。必须先用 execute_sql 获取真实数据，再调用本工具展示。",
        "parameters": {
            "type": "object",
            "properties": {
                "chart": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["column", "bar", "line", "pie", "table"]},
                        "title": {"type": "string"},
                        "x": {"type": "string"},
                        "y": {"type": "string"},
                    },
                    "required": ["type", "title", "x", "y"],
                },
                "data": {
                    "type": "object",
                    "properties": {
                        "columns": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}},
                                "required": ["name"],
                            },
                        },
                        "rows": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["columns", "rows"],
                },
                "sql": {"type": "string"},
                "chart_answer": {"type": "string"},
            },
            "required": ["chart", "data", "sql"],
        },
    },
    {
        "type": "function",
        "name": "ask_clarification",
        "description": "当用户意图模糊或信息缺失时，向用户发起追问或请求确认。",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["question"],
        },
    },
    {
        "type": "function",
        "name": "propose_subscription",
        "description": "当发现需要持续关注的指标或风险时，建议用户添加订阅/监控。",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "frequency": {"type": "string"},
                "channel": {"type": "string"},
            },
            "required": ["title", "frequency"],
        },
    },
]

# Tool names that are "result-type" (rendered as cards in result area)
RESULT_TOOLS = {"smartbot_chart", "ask_clarification", "propose_subscription", "execute_sql"}

# Tool names that are "planning-type" (rendered in planning area)
PLANNING_TOOLS = {"planning"}


def get_default_tools() -> list[dict[str, Any]]:
    """Return default tool definitions for requests that don't specify tools."""
    return [t.copy() for t in DEFAULT_TOOLS]


def is_result_tool(name: str) -> bool:
    return name in RESULT_TOOLS


def is_planning_tool(name: str) -> bool:
    return name in PLANNING_TOOLS
