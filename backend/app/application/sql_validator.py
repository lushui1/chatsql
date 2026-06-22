"""SQL safety validator — prevents destructive operations on data sources."""

from __future__ import annotations

import re


class SQLValidator:
    """SQL safety validator for ChatSQL.

    Checks:
    1. No forbidden keywords (DROP, DELETE, TRUNCATE, ALTER, CREATE, INSERT, UPDATE, etc.)
    2. No multi-statement execution
    3. No excessive subquery nesting (> 3 levels)
    4. Comments are stripped before checking
    """

    FORBIDDEN_KEYWORDS = [
        "DROP", "DELETE", "TRUNCATE", "ALTER", "CREATE", "INSERT", "UPDATE",
        "GRANT", "REVOKE", "EXEC", "EXECUTE", "xp_", "sp_",
    ]

    def validate(self, sql: str, dialect: str = "generic") -> tuple[bool, str]:
        """Validate SQL safety.

        Returns:
            (is_safe, reason) — reason is empty string if safe.
        """
        if not sql or not sql.strip():
            return False, "SQL 语句为空"

        # 1. Strip comments
        cleaned = self._strip_comments(sql)

        # 2. Check forbidden keywords (statement-level, not inside strings)
        ok, reason = self._check_forbidden_keywords(cleaned)
        if not ok:
            return False, reason

        # 3. Check multi-statement
        ok, reason = self._check_multi_statement(cleaned)
        if not ok:
            return False, reason

        # 4. Check subquery nesting depth
        ok, reason = self._check_subquery_depth(cleaned)
        if not ok:
            return False, reason

        return True, ""

    def _strip_comments(self, sql: str) -> str:
        """Remove SQL comments (-- line comments and /* block comments */)."""
        # Remove block comments
        sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
        # Remove line comments
        sql = re.sub(r'--[^\n]*', '', sql)
        return sql

    def _check_forbidden_keywords(self, sql: str) -> tuple[bool, str]:
        """Check for forbidden keywords at statement level (not inside string literals)."""
        # Remove string literals to avoid false positives
        # Handle both single-quoted and double-quoted strings
        sql_no_strings = re.sub(r"'[^']*'", "''", sql)
        sql_no_strings = re.sub(r'"[^"]*"', '""', sql_no_strings)

        # Split into tokens (case-insensitive)
        tokens = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', sql_no_strings.upper())

        for token in tokens:
            for keyword in self.FORBIDDEN_KEYWORDS:
                if keyword.endswith("_"):
                    # Prefix match (xp_, sp_)
                    if token.startswith(keyword.upper()):
                        return False, f"禁止使用危险关键字: {keyword}* (检测到: {token})"
                else:
                    # Exact match
                    if token == keyword:
                        return False, f"禁止使用危险关键字: {keyword}"

        return True, ""

    def _check_multi_statement(self, sql: str) -> tuple[bool, str]:
        """Check for multiple SQL statements (semicolons separating statements)."""
        # Remove empty segments
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        if len(statements) > 1:
            return False, f"禁止执行多条 SQL 语句 (检测到 {len(statements)} 条)"
        return True, ""

    def _check_subquery_depth(self, sql: str, max_depth: int = 3) -> tuple[bool, str]:
        """Check subquery nesting depth. Max allowed depth is max_depth."""
        depth = 0
        max_found = 0
        for char in sql:
            if char == '(':
                depth += 1
                max_found = max(max_found, depth)
            elif char == ')':
                depth = max(depth - 1, 0)

        if max_found > max_depth:
            return False, f"子查询嵌套过深 (检测到 {max_found} 层, 最大允许 {max_depth} 层)"
        return True, ""
