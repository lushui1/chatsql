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

## 本地开发启动

> `.env` 放**仓库根目录**，不是 `backend/`。
> 设置页写入的 `backend/app/data/config.json` 优先级最高，会覆盖 `.env`。

```bash
# 1. 配置（根目录）
cp .env.example .env    # 没有 .env.example 时按下面字段新建
```

```ini
CHATSQL_LLM_PROVIDER=custom
CHATSQL_LLM_API_KEY=sk-xxx
CHATSQL_LLM_BASE_URL=https://your-gateway/v1
CHATSQL_LLM_MODEL=your-model
CHATSQL_LLM_THINK_MODEL=your-model
```

```bash
# 2. 后端（必须在 backend/ 下启动，uvicorn 需要能 import app）
cd backend
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info
# Windows 之外把 .venv/Scripts/ 换成 .venv/bin/

# 3. 前端（已配置 /v1 → 8000 代理）
cd frontend && npm run dev      # http://127.0.0.1:5180

# 4. 冒烟
curl -X POST http://127.0.0.1:8000/v1/responses \
  -H 'Content-Type: application/json' -d '{"input":"各分拣中心的货量是多少？","stream":true}'
```

启动日志会打印 LLM 配置摘要（key 脱敏）：

```
INFO chatsql | LLM config: provider=custom base_url=https://... model=... key=sk-ILf...TwPr (len=51)
```

看到 `base_url=(default)` 或 `key=** 未配置 **` 说明 `.env` 没读到 —— 检查文件是否在仓库根。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.12 + FastAPI + OpenAI Agents SDK |
| OLAP | DuckDB（嵌入式零运维） |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） |
| 前端 | Vue 3 + Vite + ECharts |
| 部署 | Docker Compose |

## SQL 安全

所有进入执行链路的 SQL 都必须通过 `SQLValidator`（`backend/app/application/sql_validator.py`）：

1. **语句白名单** — 只允许 `SELECT` / `WITH` 开头；元数据接口可开 `DESCRIBE` / `SHOW` / `EXPLAIN`
2. **禁止堆叠** — 多语句一律拒绝
3. **禁止写操作** — DDL / DML / 权限语句 / 存储过程调用
4. **禁止越权读文件** — `read_csv` / `glob` / `LOAD_FILE` / `INTO OUTFILE` 等
5. **标识符校验** — 表名拼进 SQL 前必须 `sanitize_identifier`，杜绝注入
6. **自动 LIMIT** — 顶层无 `LIMIT` 时自动追加，避免全表拉取

关键实现：**所有检查都在词法掩码后的文本上做**——字符串字面量、引号标识符、
注释会先被替换成空格。否则 `WHERE status = '已签收;'` 会被误判成两条语句。

回归测试：

```bash
cd backend && python test_sql_validator.py
```

覆盖 16 条正常查询（必须放行）+ 25 条危险语句（必须拦截）+ LIMIT 追加 + 标识符注入。

## License

MIT — 见 [LICENSE](./LICENSE)

第三方来源与独立性声明见 [ATTRIBUTION.md](./ATTRIBUTION.md)。
本项目在产品设计上参考了 [SQLBot](https://github.com/dataease/SQLBot) 的功能划分思路，
但**未复制任何源码**，实现路径完全独立（详见 ATTRIBUTION.md）。
