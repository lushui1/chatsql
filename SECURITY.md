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
```

新增任何绕过手法时，先补进 `test_sql_validator.py` 的 `BLOCK_CASES`。

---

## 五、已知未覆盖项

| 项 | 说明 | 建议 |
|---|---|---|
| 查询超时 | DuckDB/MySQL 等实现均无 timeout，复杂查询可打满 CPU | 各数据源 `execute()` 加超时与取消 |
| 只读连接 | 未强制使用只读账号 | 数据源配置增加 `read_only` 选项，连接时设置 |
| SSRF | `/v1/datasources/test` 可指定任意 host/port 探测内网 | 加白名单 / 禁用内网网段 |
| 资源限额 | 无并发查询数限制 | 加信号量 |
| 审计日志 | 未记录谁在什么时候执行了什么 SQL | 建议加，出问题可追溯 |
