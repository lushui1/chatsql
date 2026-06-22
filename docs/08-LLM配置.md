# 08 — LLM 配置

## 支持的 9 种 Provider

| Provider | 默认 Base URL | 推荐模型 | 适用场景 |
|----------|-------------|---------|---------|
| openai | https://api.openai.com/v1 | gpt-4o / gpt-4o-mini | 通用，质量最高 |
| anthropic | https://api.anthropic.com | claude-sonnet-4-20250514 | 长文本，推理强 |
| google | https://generativelanguage.googleapis.com/v1beta | gemini-2.0-flash | 多模态，速度快 |
| dashscope | https://dashscope.aliyuncs.com/compatible-mode/v1 | qwen-max | 国内首选，中文好 |
| zhipu | https://open.bigmodel.cn/api/paas/v4 | glm-4-plus | 国内替代 |
| moonshot | https://api.moonshot.cn/v1 | moonshot-v1-128k | 超长上下文 |
| deepseek | https://api.deepseek.com | deepseek-chat | 性价比高 |
| ollama | http://localhost:11434 | qwen2.5:14b | 本地部署，免费 |
| custom | 用户自定义 | 用户自定义 | 接入任意 OpenAI 兼容 API |

## 配置方式

### 方式一：环境变量（.env 文件）

```bash
# .env
CHATSQL_LLM_PROVIDER=openai
CHATSQL_LLM_API_KEY=sk-xxxxx
CHATSQL_LLM_MODEL=gpt-4o-mini
CHATSQL_LLM_THINK_MODEL=gpt-4o
CHATSQL_LLM_TEMPERATURE=0.3
CHATSQL_LLM_MAX_TOKENS=4096
```

### 方式二：API 热更新（不重启生效）

```bash
# 查看当前配置
curl http://127.0.0.1:8000/v1/config/llm

# 更新配置
curl -X POST http://127.0.0.1:8000/v1/config/llm \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "dashscope",
    "api_key": "sk-xxxxx",
    "model": "qwen-max",
    "temperature": 0.5
  }'
```

### 方式三：前端设置面板

打开设置 → 🤖 大模型 Tab → 选择 Provider → 填 Key 和模型 → 💾 保存

## 运行时热切换

LLM 配置修改后立即生效，无需重启后端：

```
用户修改 Provider: openai → dashscope
    │
    ▼
POST /v1/config/llm
    │
    ▼
更新 _settings 对象 + 写入 data/config.json
    │
    ▼
下次对话自动使用新 Provider
```

**持久化**：配置同时写入 `data/config.json`，重启后自动加载。

## fast 模型 vs think 模型

| 维度 | fast 模型 | think 模型 |
|------|----------|-----------|
| 配置字段 | `model` | `think_model` |
| 使用场景 | fast 模式对话 | think 模式对话 |
| 速度要求 | 快（1-3秒） | 可以慢（5-30秒） |
| 质量要求 | 够用 | 尽量高 |
| Token 消耗 | 低 | 高 |
| 典型选择 | gpt-4o-mini / qwen-turbo | gpt-4o / deepseek-r1 / qwen-max |

### 模式切换时的模型选择

```
用户选择 fast 模式 → 使用 model 配置
用户选择 think 模式 → 使用 think_model 配置
think_model 未配置 → 回退到 model
```

## 自定义 Provider 接入

任何兼容 OpenAI API 格式的服务都可以通过 `custom` Provider 接入：

```json
{
  "provider": "custom",
  "api_key": "your-key",
  "base_url": "https://your-api-server.com/v1",
  "model": "your-model-name"
}
```

### 兼容性要求

自定义 Provider 需要支持：
- `POST /chat/completions` 接口
- `stream: true` 参数（SSE 流式返回）
- OpenAI 格式的 message 结构

### 常见自定义 Provider

| 服务 | base_url | 说明 |
|------|---------|------|
| vLLM | http://localhost:8000/v1 | 本地模型服务 |
| LiteLLM | http://localhost:4000 | 统一代理 |
| OneAPI | http://localhost:3000/v1 | 多 Key 管理 |
| OpenRouter | https://openrouter.ai/api/v1 | 模型聚合 |
