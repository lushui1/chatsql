# ATTRIBUTION — 第三方来源与独立性声明

本项目 **ChatSQL** 采用 MIT 协议（见 `LICENSE`）。
本文件说明本项目在设计中参考过的外部项目，以及为什么这**不构成**代码复制。

> 目的：既不隐瞒参考来源，也不让 MIT 声明建立在含糊之上。
> 后面若要引入任何第三方源码，必须先在此登记并核对协议兼容性。

---

## 一、设计参考（无代码复制）

### SQLBot

- 项目：https://github.com/dataease/SQLBot
- 作者：飞致云（FIT2CLOUD）/ DataEase 团队
- 协议：**FIT2CLOUD Open Source License**（基于 GPLv3，额外要求保留 Logo 与版权声明）

**参考了什么**：产品形态与功能模块的划分思路。
2026-06-22 的提交 `f55efa0 feat: SQLBot融合` 引入的四项能力，对应 SQLBot 的概念层设计：

| 本项目模块 | 对应的 SQLBot 概念 |
|---|---|
| 业务上下文 | 术语库 / Terminology |
| RAG 检索 | 知识库 embedding 检索 |
| 仪表盘 | Dashboard |
| 侧边导航重构 | 界面信息架构 |

**没有参考什么**：任何源码、文件结构、变量名。

### 独立于 SQLBot 的实现证据

技术栈在两个项目间没有交集，代码不可能互相搬运：

| 能力 | SQLBot | ChatSQL |
|---|---|---|
| LLM 框架 | LangChain | 自写 Provider 抽象（`application/llm/`） |
| 向量检索 | sentence-transformers + pgvector | 纯 Python：TF-IDF + 关键词 + 编辑距离（`rag_service.py`） |
| 前端 UI | Vue3 + Element Plus + Pinia + Router | 裸 Vue，未引入任何组件库 |
| 图表 | AntV G2 + SSR 服务 | ECharts |
| ORM | SQLModel + Alembic 迁移 | SQLAlchemy，无迁移 |
| 元数据库 | PostgreSQL | SQLite |

`rag_service.py` 文件头即为明证：

```
Pure Python implementation — TF-IDF + keyword matching + edit distance.
No vector database.
```

这是看完"RAG 用于问数"这个思路后的自主实现——它没有用 embedding，没有用向量库，
和 SQLBot 的实现路径完全不同。

### 结论

- ✅ 未复制、未修改、未分发 SQLBot 源码
- ✅ 未使用 SQLBot 的 Logo、商标或版权素材
- ✅ ChatSQL 不是 SQLBot 的衍生作品，因此不受 GPLv3 / FIT2CLOUD 协议的传染性约束
- ✅ MIT 声明成立

---

## 二、待办：如果将来要引入 SQLBot 源码

FIT2CLOUD License 与 MIT **不兼容**。若未来决定直接复用 SQLBot 的模块
（尤其是 `terminology/`、`datasource/embedding/`），必须二选一：

1. **放弃 MIT**，整个项目改为 FIT2CLOUD Open Source License，并保留其 Logo 与版权声明；
2. **保持 MIT**，则只能参考其接口设计与交互，自己重写实现（当前做法）。

在此之前，任何从 SQLBot 复制文件的行为都会使本项目的 MIT 声明失效。

---

## 三、自有代码来源

本项目底层源自作者本人的 **SmartBot** 项目（内部工具，未对外发布）。
仓库中残留的 `smartbot_` 命名已统一为 `chatsql_`，
仅保留 `X-SmartBot-Mode` 作为 HTTP 请求头的兼容别名（见 `auth_utils.py`）。

---

## 四、第三方依赖

后端见 `backend/pyproject.toml`，前端见 `frontend/package.json`。
所有依赖均通过包管理器引入，遵循各自开源协议，未内置任何 vendored 源码。
