# 09 — API 参考

## 基础信息

```
Base URL: http://127.0.0.1:8000
Content-Type: application/json
认证: 暂无（开发阶段），后续支持 API Key
```

## 核心对话接口

### POST /v1/responses

发送消息并获取 Agent 回复（支持 SSE 流式和非流式）。

**请求头**：
| Header | 说明 | 示例 |
|--------|------|------|
| X-Session-Id | 会话 ID（可选，不传则自动创建） | `sess_abc123` |
| X-SmartBot-Mode | 模式 | `fast` 或 `think` |
| Accept | 响应格式 | `text/event-stream`（流式）或 `application/json` |

**请求体**：
```json
{
  "model": "gpt-4o-mini",
  "input": [
    {"role": "user", "content": "最近7天的订单量趋势"}
  ],
  "stream": true,
  "tools": [
    {"type": "function", "name": "planning"},
    {"type": "function", "name": "smartbot_chart"},
    {"type": "function", "name": "ask_clarification"},
    {"type": "function", "name": "propose_subscription"}
  ]
}
```

**SSE 流式响应事件类型**：

| 事件 | 说明 | 关键字段 |
|------|------|---------|
| `response.created` | 响应创建 | `response.id`, `response.session_id` |
| `response.in_progress` | 处理中 | — |
| `response.output_item.added` | 输出项新增 | `item.type` (function_call/message) |
| `response.output_text.delta` | 文本增量 | `delta` (文本片段) |
| `response.function_call_arguments.delta` | 工具参数增量 | `call_id`, `delta` |
| `response.function_call_arguments.done` | 工具参数完成 | `call_id`, `name`, `arguments` |
| `response.completed` | 响应完成 | `response.output` (完整输出) |
| `response.failed` | 响应失败 | `error` |

**非流式响应**：
```json
{
  "id": "resp_abc123",
  "session_id": "sess_xyz",
  "output": [
    {
      "type": "function_call",
      "name": "planning",
      "arguments": "{\"overview\":\"...\",\"steps\":[...]}"
    },
    {
      "type": "message",
      "role": "assistant",
      "content": [{"type": "output_text", "text": "查询结果..."}]
    }
  ],
  "status": "completed"
}
```

## 会话管理

### GET /v1/sessions

获取会话列表。

**响应**：
```json
[
  {
    "id": "sess_abc123",
    "title": "最近7天订单量趋势",
    "mode": "fast",
    "streaming": false,
    "created_at": "2026-06-18T10:00:00Z"
  }
]
```

### DELETE /v1/sessions/{session_id}

删除会话及其所有消息。

### GET /v1/sessions/{session_id}/response-turns

获取会话的消息轮次（分页）。

**查询参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| limit | int | 每页数量（默认 20） |
| cursor | string | 分页游标 |
| direction | string | `forward` 或 `backward` |

## 数据源管理

### GET /v1/datasources

获取已配置的数据源列表。

### POST /v1/datasources

添加数据源。

**请求体**：
```json
{
  "name": "my_mysql",
  "type": "mysql",
  "host": "192.168.1.100",
  "port": 3306,
  "database": "orders_db",
  "username": "reader",
  "password": "******"
}
```

### POST /v1/datasources/test

测试数据源连接（不保存）。

**请求体**：同上

**响应**：
```json
{
  "ok": true,
  "message": "连接成功，发现 5 张表",
  "tables": ["orders", "users", "products", "routes", "sort_center"]
}
```

### DELETE /v1/datasources/{name}

删除数据源。

### GET /v1/datasources/{name}/metadata

获取数据源的完整元数据（所有表的结构）。

## LLM 配置

### GET /v1/config/llm

获取当前 LLM 配置（API Key 脱敏）。

**响应**：
```json
{
  "provider": "openai",
  "model": "gpt-4o-mini",
  "think_model": "gpt-4o",
  "base_url": "https://api.openai.com/v1",
  "api_key_masked": "sk-****abcd",
  "temperature": 0.3,
  "max_tokens": 4096,
  "available_providers": ["openai", "anthropic", "google", "..."],
  "provider_models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"]
}
```

### POST /v1/config/llm

更新 LLM 配置（热生效 + 持久化）。

## 学习系统

### GET /v1/learn/routines

获取已学习的规则列表。

### GET /v1/learn/stats

获取学习统计信息。

### POST /v1/learn/trigger

手动触发经验蒸馏。

## 系统端点

### GET /healthz

健康检查。

```json
{"ok": true, "service": "chatsql"}
```

### GET /readyz

就绪检查。

```json
{"ok": true, "service": "chatsql", "version": "0.1.0"}
```

## 完整端点列表（21个）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /v1/responses | 核心对话（SSE 流式） |
| GET | /v1/sessions | 会话列表 |
| DELETE | /v1/sessions/{id} | 删除会话 |
| GET | /v1/sessions/{id}/response-turns | 消息轮次 |
| POST | /v1/sessions/{id}/feedback | 提交反馈 |
| GET | /v1/config/llm | 获取 LLM 配置 |
| POST | /v1/config/llm | 更新 LLM 配置 |
| GET | /v1/datasources | 数据源列表 |
| POST | /v1/datasources | 添加数据源 |
| POST | /v1/datasources/test | 测试连接 |
| DELETE | /v1/datasources/{name} | 删除数据源 |
| GET | /v1/datasources/{name}/metadata | 元数据 |
| GET | /v1/learn/routines | 学习规则列表 |
| POST | /v1/learn/routines | 创建规则 |
| GET | /v1/learn/routines/{id} | 规则详情 |
| PUT | /v1/learn/routines/{id} | 更新规则 |
| DELETE | /v1/learn/routines/{id} | 删除规则 |
| GET | /v1/learn/stats | 学习统计 |
| POST | /v1/learn/trigger | 触发蒸馏 |
| GET | /healthz | 健康检查 |
| GET | /readyz | 就绪检查 |
