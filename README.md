# ChatSQL — Open-source ChatBI Framework

一个开源的智能问数（ChatBI）框架，让任何企业5分钟内接入自己的数据库，用自然语言查数据。

## 特性

- 🔌 **OpenAI Responses API 兼容** — 标准接口，任何 OpenAI 客户端可直接对接
- 📊 **多数据源插件** — DuckDB / MySQL / PostgreSQL / ClickHouse
- 🤖 **LLM 多 Provider** — OpenAI / 通义千问 / Ollama 本地部署
- 💬 **SSE 流式输出 + 断线续接** — 生产级流式体验
- 🧠 **双模式** — fast（快速查询）/ think（深度分析）
- 📋 **规划区 + 结果区** — 可视化分析步骤，图表独立渲染
- 🔧 **4个内置 Function Tools** — planning / chart / clarification / subscription
- 🐳 **Docker 一键部署** — 零运维

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/lushui1/chatsql.git
cd chatsql

# 2. 配置
cp .env.example .env
# 编辑 .env 填入 LLM API Key

# 3. 启动
docker compose up -d

# 4. 访问
open http://localhost:8080
```

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.12 + FastAPI + OpenAI Agents SDK |
| OLAP | DuckDB（嵌入式零运维） |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） |
| 前端 | Vue 3 + Vite + ECharts |
| 部署 | Docker Compose |

## License

MIT
