# SECURITY — SQL 安全模型与修复记录

## 一、威胁模型

ChatSQL 的核心风险：**让 LLM（以及通过 HTTP 的任何人）向生产数据库发送任意 SQL**。

三条攻击路径：

| 路径 | 谁能触发 | 风险 |
|---|---|---|
| LLM 生成 SQL | 任何提问的用户（通过 prompt 注入诱导） | 删库、拖库、读服务器文件 |
| `/v1/datasources/execute` | 任何能访问 API 的人 | 同上，且无任何中间层 |
| 元数据接口的表名参数 | 同上 | SQL 注入（`DESCRIBE {table}`） |

因此防线必须**部署在执行出口，而不是寄希望于提示词**。

---

## 二、当前防线（三道，纵深部署）

```
用户提问 → LLM 生成 SQL
   ↓
[1] responses_service._execute_sql    校验 + 自动 LIMIT
   ↓
[2] DataSourceManager.execute         校验（唯一出口，兜底所有调用方）
   ↓
[3] 数据库
```

另有两条横向防线：

- **元数据接口**：表名进 SQL 前必须过 `sanitize_identifier`
- **HTTP 执行端点**：独立 validator（放行 DESCRIBE/SHOW）+ 强制 LIMIT + 结果截断

### 检查项（`backend/app/application/sql_validator.py`）

| # | 检查 | 说明 |
|---|---|---|
| 1 | 语句白名单 | 必须以 `SELECT` / `WITH` 开头 |
| 2 | 禁止堆叠 | 掩码后按 `;` 切分，>1 条即拒 |
| 3 | 危险关键字 | DDL / DML / 权限 / 存储过程 |
| 4 | 危险写法 | `REPLACE INTO`、`INTO OUTFILE`、`LOAD_FILE`、`COPY ... FROM` |
| 5 | 文件/系统调用 | `read_csv`、`read_parquet`、`glob`、`pg_sleep` 等 |
| 6 | 子查询深度 | 上限 5 层（防 DoS） |
| 7 | 字面量闭合 | 未闭合的字符串直接拒绝 |

### 关键实现：所有检查都在词法掩码后的文本上做

`_mask_sql()` 把字符串字面量、引号标识符、`--` / `#` / `/* */` 注释
统一替换成空格，再交给后续检查。

**为什么必须这样**：下面这条完全正常的查询，旧实现会误判成两条语句并拦截——

```sql
SELECT * FROM orders WHERE status = '已签收;'
```

反过来，不做掩码也会**放行**绕过：

```sql
SELECT 1 -- x
; DROP TABLE orders
```

掩码后第一行是 `SELECT 1  `，分号暴露 → 被多语句检查拦下。

### 规则单一事实来源

prompt 里告诉模型的 SQL 规则，**由校验器自己生成**（`SQLValidator.describe_rules()`），
而不是手写在 prompt 里。

原因：二者一旦不同步就会出问题。修复前 prompt 写"子查询嵌套不超过 3 层"，
而校验器实际允许 5 层——模型按 3 层约束自己，白白损失表达能力；
反过来若 prompt 比校验器宽松，模型会生成被拒的 SQL，用户只看到"校验不通过"。

现在改 `FORBIDDEN_KEYWORDS` / `_MAX_SUBQUERY_DEPTH`，prompt 自动跟着变。

---

## 三、本次修复清单

| # | 问题 | 严重度 | 修复 |
|---|---|---|---|
| 1 | `/v1/datasources/execute` **完全不校验 SQL**，POST 任意语句即执行 | **P0** | 接入 validator + 强制 LIMIT + 结果截断 |
| 2 | 8 个数据源实现的 `DESCRIBE {table}` / `COUNT(*) FROM {table}` 直接 f-string 拼接 | **P0** | manager 入口统一 `sanitize_identifier`；DuckDB 实现改用 `quote_identifier` |
| 3 | `split(";")` 判断多语句，字符串内分号造成误判 | P1 | 改为词法掩码后切分 |
| 4 | 正则 `'`[^'] `*'` 去字符串，不处理 `''` 转义 | P1 | 改为字符级扫描器 |
| 5 | `--[^\n]*` 去注释，误伤字符串里的 `--` | P1 | 同上 |
| 6 | 子查询深度在未去字符串的原文本上统计 | P2 | 改为掩码后统计 |
| 7 | `"LIMIT" not in sql.upper()` 判断是否需要加 LIMIT：子查询有 LIMIT 时不加（可能拉全表）；字符串含 "limit" 时不加 | P1 | `enforce_limit()` 只在括号深度 0 处找 LIMIT |
| 8 | `DataSourceManager.execute` 无任何校验，新增调用方容易漏 | P1 | 在唯一出口加兜底校验 |
| 9 | 前端 `vue-tsc` 类型错误导致构建失败（既有） | P2 | 修 `Sidebar.vue` / `SettingsView.vue` 类型收窄 |
| 10 | `/v1/datasources/execute` 绕过 `manager.execute` 直连 `ds.execute()`，并发限流形同虚设 | P1 | 改走统一 limiter + `run_async` |

### 顺带发现的认知点

**黑名单会误伤正常函数。** 初版把 `REPLACE` 放进关键字黑名单，结果
`TRIM(REPLACE(status,';',''))` 这种标准清洗写法被拦。`REPLACE` 只有跟 `INTO`
连用（`REPLACE INTO`）才是 MySQL 写操作。结论：双关词必须按上下文判断，
不能只看 token。

**白名单要防 `WITH`。** PostgreSQL 的数据修改 CTE 以 `WITH` 开头：

```sql
WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d
```

能过语句白名单，只能靠关键字黑名单里的 `DELETE` 兜底。这也是黑名单
不能全删的原因——它和白名单是互补的，不是替代关系。

---

## 四、回归测试

```bash
cd backend
python test_sql_validator.py    # 47 项：16 放行 + 25 拦截 + LIMIT + 标识符注入
python test_security_smoke.py   # 20 项：真实 DuckDB 上的端到端验证
python test_llm_retry.py        # 12 项：LLM 重试 / 退避 / 不重复输出
python test_query_timeout.py    # 19 项：超时 / 取消 / 并发 / 行数截断
```

新增任何绕过手法时，先补进 `test_sql_validator.py` 的 `BLOCK_CASES`。

---

## 四·补、LLM 调用的重试与退避

链路默认**没有**重试、退避和显式超时。批量或并发场景下一旦触发网关 QPM
限制，连续 429 会把整批请求打爆，且失败集中在后半段——如果不处理，很容易
得出"改了 prompt 反而变差"这种完全错误的结论（这点在 smartqa 评测中真实发生过：
v2 组后 19 题全部因限流失败，差点误判为负面结果）。

策略（`backend/app/application/llm/__init__.py`）：

| 项 | 值 |
|---|---|
| 重试次数 | 3 次 |
| 退避 | 1.5s / 4s / 10s |
| 请求超时 | 120s（建连 10s） |
| 可重试 | 408/409/425/429/5xx + 限流与超时类异常 |
| 不重试 | 4xx 客户端错误（400/401/403…） |
| SDK 内部重试 | 关闭（`max_retries=0`），避免退避时间不可控 |

**流式安全约束**：只有**还没吐出任何内容**时才允许重试。
一旦已经向前端 yield 过 chunk 再失败，重试会造成重复文本，此时直接抛出。
这条由 `test_llm_retry.py` 的第 2 组用例专门守护。

---

## 四·补、执行层资源闸门（query_guard）

校验器只管「非法」，管不了「合法但昂贵」。一条笛卡尔积、一次无 LIMIT 的
全表聚合，语法正确、权限也合法，但能打满 CPU 或撑爆内存。

`backend/app/application/datasources/query_guard.py` 提供四道闸：

| 闸门 | 默认值 | 配置键 |
|---|---|---|
| 单查询超时 | 30s | `CHATSQL_QUERY_TIMEOUT_SECONDS` |
| 结果集行数 | 10,000（超出截断并标注） | `CHATSQL_QUERY_MAX_ROWS` |
| 全局并发查询 | 8 | `CHATSQL_QUERY_MAX_CONCURRENCY` |
| 超时后取消 | — | 各驱动的中断接口 |

**最关键的是"取消"必须真的取消。** `asyncio.wait_for` 取消的只是 Future，
线程里阻塞执行的驱动调用根本不会被打断——查询仍在数据库里跑，只是调用方
不等了。所以超时后必须调驱动自己的中断接口：

| 数据源 | 中断手段 |
|---|---|
| DuckDB | `cursor.interrupt()`（每个查询独立 cursor，中断后不影响后续查询） |
| PostgreSQL | `conn.fetch(sql, timeout=t)` 发 CancelRequest + `conn.terminate()` 兜底 |
| MySQL / Doris | 物理 `conn.close()`，且不归还连接池（脏连接不能复用） |
| ClickHouse | 服务端 `max_execution_time` + 客户端丢弃连接 |
| Hive / Presto / Spark | 没有中断接口，只能断开连接并丢弃（下次重建） |

`manager.execute` 是唯一出口，在此统一施加；各数据源实现自己也有一层，
双保险防止将来实现漏加。

---

## 五、已知未覆盖项

| 项 | 说明 | 建议 |
|---|---|---|
| 只读连接 | 未强制使用只读账号 | 数据源配置增加 `read_only` 选项，连接时设置 |
| SSRF | `/v1/datasources/test` 可指定任意 host/port 探测内网 | 加白名单 / 禁用内网网段 |
| 资源限额 | 无并发查询数限制 | 加信号量 |
| 审计日志 | 未记录谁在什么时候执行了什么 SQL | 建议加，出问题可追溯 |
| Anthropic / Google 重试 | 本次只给 OpenAI 兼容链路加了重试 | 按同一模式补上 |
| 评测集 | 改动 prompt / 元数据后没有量化验证手段 | 见下 |

## 六、待建：问数评测集

目前改动 prompt 或元数据后，**没有量化手段判断是变好还是变坏**。

在 smartqa（同作者的对照实验项目）里，唯一能证明"元数据治理有效"的就是
一套 30 题评测集（10 高频 / 10 模糊 / 10 陷阱）+ golden SQL + 归因报告。
它的价值不在于跑分，而在于**能区分"算错"和"形状不同"**，以及**能发现
golden 答案自身的 bug**（曾出现模型答对、标准答案错了的反例）。

建议后续按同一套方法给 chatsql 建评测：
`eval/eval_set.yaml`（问题 + golden SQL + 期望）+ `run_eval.py`
（跑分 + 按类别统计）+ `report.py`（错题归因）。
