"""SQL safety validator — prevents destructive operations on data sources.

设计原则：白名单优先，黑名单兜底。

1. 先做**词法掩码**：把字符串字面量、引号标识符、注释全部替换成空格，
   得到一份"结构等价"的 SQL。后续所有检查只在掩码后的文本上做。
   这样 `status='已签收;'` 里的分号、`note='a--b'` 里的 `--`
   都不会被误判，也不会被用来绕过检查。

   > 历史 bug：旧实现用 `sql.split(";")` 判断多语句、用正则
   > `--[^\\n]*` 去注释、用 `'[^']*'` 去字符串，三者都不处理
   > 转义与嵌套，导致正常查询被拦截（见 test_sql_validator.py）。

2. 再检查：语句类型白名单 → 单语句 → 危险关键字 → 子查询深度。
"""

from __future__ import annotations

import re

# 标识符单段允许的字符集：字母/数字/下划线/$/中文，不含点、空格、引号、分号、减号。
# \w 在 Python3 默认含 Unicode（中文表名合法），但要排除 [.-;'" 等注入字符。
_IDENT_SEG_RE = re.compile(r"^[^\W\d]\w*$", re.UNICODE)

# 子查询嵌套上限。describe_rules() 会把它写进 prompt，
# 保证「提示词里的数字」与「校验器实际执行的数字」永远一致。
_MAX_SUBQUERY_DEPTH = 5

# 各库的标识符引用符
_QUOTE_BY_DIALECT = {
    "duckdb": '"', "postgresql": '"', "postgres": '"', "sqlite": '"',
    "presto": '"', "trino": '"', "hive": "`", "spark": "`", "doris": "`",
    "mysql": "`", "clickhouse": "`",
}


class SQLValidator:
    """SQL safety validator for ChatSQL.

    Checks:
    1. Statement type must be in the allowlist (SELECT / WITH by default)
    2. No multi-statement execution
    3. No forbidden keywords (DROP, DELETE, TRUNCATE, ALTER, ...)
    4. No excessive subquery nesting
    """

    # 语句类型白名单：默认只允许纯查询
    ALLOWED_STATEMENT_PREFIXES = ("SELECT", "WITH")
    # 可选的只读管理语句，需显式开启
    EXTRA_READONLY_PREFIXES = ("DESCRIBE", "DESC", "SHOW", "EXPLAIN")

    # token 级精确匹配。注意：只放"出现在任何位置都危险"的词。
    # REPLACE / SET / LOAD / MERGE 这类双关词不能放这里——
    # REPLACE() 是常见字符串函数，UPDATE ... SET 是合法语法，
    # 它们用下面的 FORBIDDEN_PHRASES 按上下文判断。
    FORBIDDEN_KEYWORDS = [
        "DROP", "DELETE", "TRUNCATE", "ALTER", "CREATE", "INSERT", "UPDATE",
        "GRANT", "REVOKE", "EXEC", "EXECUTE",
    ]

    # 上下文相关的危险写法（正则，作用在掩码后的文本上）
    FORBIDDEN_PHRASES = [
        r"\bREPLACE\s+INTO\b",          # MySQL 的 REPLACE INTO
        r"\bINTO\s+(OUTFILE|DUMPFILE)\b",  # MySQL 写文件
        r"\bLOAD_(FILE|DATA)\b",        # MySQL 读/写文件
        r"\bpg_(read_file|ls_dir|logdir_ls)\b",  # PostgreSQL 文件访问
        r"\bCOPY\s+\w+\s+FROM\s+",      # PostgreSQL COPY FROM（读文件）
    ]

    # 文件读取类函数 —— 问数场景不需要，属于越权读本地文件
    FORBIDDEN_FUNCTIONS = [
        "READ_CSV", "READ_CSV_AUTO", "READ_PARQUET", "READ_TEXT",
        "READ_JSON", "READ_JSON_AUTO", "READ_BLOB", "GLOB",
        "SLEEP", "PG_SLEEP",
    ]

    # 前缀匹配型（存储过程 / 扩展函数）
    FORBIDDEN_PREFIXES = ["XP_", "SP_"]

    def __init__(self, allow_readonly_admin: bool = False,
                 backslash_escapes: bool = True):
        """
        Args:
            allow_readonly_admin: 允许 DESCRIBE / SHOW / EXPLAIN 等只读管理语句。
                                  仅供内部元数据接口使用，LLM 生成链路保持 False。
            backslash_escapes:    是否把反斜杠当作字符串内转义符（MySQL 风格）。
                                  开启时 `'a\\'` 会被正确识别为已闭合。
        """
        self.allow_readonly_admin = allow_readonly_admin
        self.backslash_escapes = backslash_escapes

    # ── 公开 API ──────────────────────────────────────────────

    def validate(self, sql: str, dialect: str = "generic") -> tuple[bool, str]:
        """Validate SQL safety.

        Returns:
            (is_safe, reason) — reason is empty string if safe.
        """
        if not sql or not sql.strip():
            return False, "SQL 语句为空"

        # 1. 词法掩码：去注释 + 去字符串 + 去引号标识符
        masked, err = self._mask_sql(sql)
        if err:
            return False, err

        # 2. 语句类型白名单
        ok, reason = self._check_statement_type(masked)
        if not ok:
            return False, reason

        # 3. 单语句
        ok, reason = self._check_single_statement(masked)
        if not ok:
            return False, reason

        # 4. 危险关键字
        ok, reason = self._check_forbidden_keywords(masked)
        if not ok:
            return False, reason

        # 5. 子查询嵌套深度
        ok, reason = self._check_subquery_depth(masked)
        if not ok:
            return False, reason

        return True, ""

    @classmethod
    def describe_rules(cls) -> str:
        """生成给 LLM 看的 SQL 规则文本。

        单一事实来源：规则内容由校验器的实际配置推导，避免
        "prompt 里写 3 层、校验器允许 5 层"这种不同步。
        改校验器，prompt 自动跟着变。
        """
        keywords = " / ".join(cls.FORBIDDEN_KEYWORDS)
        return (
            "## SQL 书写规则\n"
            f"1. 只允许 {' / '.join(cls.ALLOWED_STATEMENT_PREFIXES)} 语句，"
            f"禁止 {keywords}\n"
            "2. 一条 SQL 只做一件事，禁止用分号拼接多条语句\n"
            f"3. 子查询嵌套不超过 {_MAX_SUBQUERY_DEPTH} 层\n"
            "4. 表名、字段名只使用下面给出的表结构，不要臆造\n"
        )

    @staticmethod
    def sanitize_identifier(name: str) -> str:
        """校验标识符合法，非法则抛 ValueError。

        用于任何需要把标识符拼进 SQL 的地方（DESCRIBE xxx、SHOW COLUMNS FROM xxx）。
        直接 f-string 拼接表名 = SQL 注入。

        支持 schema.table 形式的限定名，每段独立校验。
        """
        if not name or not name.strip():
            raise ValueError("标识符为空")

        parts = name.split(".")
        if len(parts) > 3:
            raise ValueError(f"标识符层级过多: {name!r}")

        for p in parts:
            if not p or not _IDENT_SEG_RE.match(p):
                raise ValueError(f"非法标识符: {name!r}（不合法段: {p!r}）")
        return name

    @staticmethod
    def quote_identifier(name: str, dialect: str = "duckdb") -> str:
        """校验并加引号包裹，返回可直接拼进 SQL 的安全标识符。

        例: quote_identifier('orders', 'duckdb')      -> '"orders"'
            quote_identifier('main.orders', 'duckdb') -> '"main"."orders"'
        """
        SQLValidator.sanitize_identifier(name)
        q = _QUOTE_BY_DIALECT.get(dialect.lower(), '"')
        return ".".join(f"{q}{p}{q}" for p in name.split("."))

    def enforce_limit(self, sql: str, limit: int = 1000) -> str:
        """若顶层语句没有 LIMIT，则追加 LIMIT。

        只在括号深度为 0 的位置寻找 LIMIT，避免"子查询里有 LIMIT
        就不给外层加"的漏判（旧实现用 `"LIMIT" not in sql.upper()`）。
        """
        masked, err = self._mask_sql(sql)
        if err:
            return sql

        depth = 0
        found = False
        for m in re.finditer(r"([()])|(\bLIMIT\b)", masked, re.IGNORECASE):
            if m.group(1) == "(":
                depth += 1
            elif m.group(1) == ")":
                depth = max(depth - 1, 0)
            elif m.group(2) and depth == 0:
                found = True
                break

        if found:
            return sql
        return sql.strip().rstrip(";").rstrip() + f" LIMIT {int(limit)}"

    # ── 词法掩码 ──────────────────────────────────────────────

    def _mask_sql(self, sql: str) -> tuple[str, str]:
        """把注释 / 字符串 / 引号标识符替换成空格。

        Returns:
            (masked_sql, error) — error 非空表示字面量未闭合等严重问题。
        """
        out: list[str] = []
        i, n = 0, len(sql)

        while i < n:
            c = sql[i]
            nxt = sql[i + 1] if i + 1 < n else ""

            # 行注释 --
            if c == "-" and nxt == "-":
                j = sql.find("\n", i)
                j = n if j == -1 else j
                out.append(" ")
                i = j
                continue

            # MySQL 风格 # 注释
            if c == "#":
                j = sql.find("\n", i)
                j = n if j == -1 else j
                out.append(" ")
                i = j
                continue

            # 块注释 /* ... */
            if c == "/" and nxt == "*":
                j = sql.find("*/", i + 2)
                j = n if j == -1 else j + 2
                out.append(" ")
                i = j
                continue

            # 引号（字符串 / 标识符）
            if c in ("'", '"', "`"):
                end = self._consume_quoted(sql, i, c)
                if end < 0:
                    return "", f"SQL 字面量未闭合 (起始于第 {i + 1} 个字符): {c}"
                out.append(" ")
                i = end
                continue

            # SQL Server 风格 [identifier]
            if c == "[":
                j = sql.find("]", i)
                if j == -1:
                    return "", f"SQL 标识符未闭合 (起始于第 {i + 1} 个字符): ["
                out.append(" ")
                i = j + 1
                continue

            out.append(c)
            i += 1

        return "".join(out), ""

    def _consume_quoted(self, sql: str, start: int, quote: str) -> int:
        """从 start（指向开引号）扫描到闭引号，返回闭引号后一位；未闭合返回 -1。"""
        i = start + 1
        n = len(sql)
        while i < n:
            c = sql[i]
            if c == "\\" and self.backslash_escapes:
                i += 2
                continue
            if c == quote:
                # SQL 标准：连续两个引号表示一个字面引号
                if i + 1 < n and sql[i + 1] == quote:
                    i += 2
                    continue
                return i + 1
            i += 1
        return -1

    # ── 各项检查 ──────────────────────────────────────────────

    def _check_statement_type(self, masked: str) -> tuple[bool, str]:
        """语句必须以白名单开头。

        这是最可靠的防线：不管后面藏了多少花招，
        只要第一个词不是 SELECT/WITH，直接拒绝。
        """
        m = re.search(r"\S", masked)
        if not m:
            return False, "SQL 语句为空（注释或字面量之外没有内容）"

        head = masked[m.start():m.start() + 12].upper()
        allowed = list(self.ALLOWED_STATEMENT_PREFIXES)
        if self.allow_readonly_admin:
            allowed += list(self.EXTRA_READONLY_PREFIXES)

        for p in allowed:
            # 用单词边界，避免 SELECTXYZ 之类蒙混过关
            if re.match(rf"^{p}\b", head):
                return True, ""
        return False, (
            f"只允许查询类语句 ({'/'.join(allowed)})，"
            f"实际以 '{head.strip()[:12]}' 开头"
        )

    def _check_single_statement(self, masked: str) -> tuple[bool, str]:
        """掩码后按分号切分，正常字面量里的分号已被剔除。"""
        statements = [s.strip() for s in masked.split(";") if s.strip()]
        if len(statements) > 1:
            return False, f"禁止执行多条 SQL 语句 (检测到 {len(statements)} 条)"
        return True, ""

    def _check_forbidden_keywords(self, masked: str) -> tuple[bool, str]:
        """三类匹配：精确 token、上下文短语、函数名。全在掩码后的文本上做。

        这条检查同时是 WITH 语句的兜底 —— PostgreSQL 的数据修改 CTE
        （`WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d`）
        以 WITH 开头能过白名单，只能靠这里的 DELETE 拦截。
        """
        upper = masked.upper()

        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", upper):
            if token in self.FORBIDDEN_KEYWORDS:
                return False, f"禁止使用危险关键字: {token}"
            if token in self.FORBIDDEN_FUNCTIONS:
                return False, f"禁止使用文件/系统调用函数: {token}"
            for prefix in self.FORBIDDEN_PREFIXES:
                if token.startswith(prefix):
                    return False, f"禁止使用危险调用: {prefix}* (检测到: {token})"

        for pattern in self.FORBIDDEN_PHRASES:
            if re.search(pattern, upper):
                return False, f"禁止使用危险写法: {pattern}"

        return True, ""

    def _check_subquery_depth(self, masked: str, max_depth: int = _MAX_SUBQUERY_DEPTH) -> tuple[bool, str]:
        """括号深度检查（在掩码文本上做，字符串里的括号不计数）。"""
        depth = 0
        max_found = 0
        for char in masked:
            if char == "(":
                depth += 1
                max_found = max(max_found, depth)
            elif char == ")":
                depth = max(depth - 1, 0)

        if max_found > max_depth:
            return False, f"子查询嵌套过深 (检测到 {max_found} 层, 最大允许 {max_depth} 层)"
        return True, ""
