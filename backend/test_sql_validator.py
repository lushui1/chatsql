"""SQLValidator 回归测试。

分两类：
- PASS 组：正常查询，**必须**通过（旧实现在这里误判过）
- BLOCK 组：危险语句，**必须**拦截

运行： pytest backend/test_sql_validator.py -v
或：   python backend/test_sql_validator.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.application.sql_validator import SQLValidator  # noqa: E402


# ── PASS：正常查询，必须放行 ──────────────────────────────────

PASS_CASES = [
    ("最简单查询", "SELECT 1"),
    ("带 WHERE", "SELECT * FROM orders WHERE city = '北京'"),
    ("带尾分号", "SELECT * FROM orders;"),
    ("CTE", "WITH t AS (SELECT 1 AS a) SELECT * FROM t"),
    # ↓ 以下 4 条是旧实现的误判重灾区
    ("字符串内含分号", "SELECT * FROM orders WHERE status = '已签收;'"),
    ("字符串内含行注释符", "SELECT * FROM t WHERE note = 'a--b'"),
    ("字符串内含块注释符", "SELECT * FROM t WHERE note = 'a/*b*/c'"),
    ("字符串内含 DROP", "SELECT * FROM t WHERE name = 'DROP TABLE x'"),
    ("字符串内转义引号", "SELECT 'it''s ok' AS a"),
    ("反斜杠转义后正常闭合", "SELECT 'don\\'t' AS a, 1 AS b"),
    ("真实清洗写法", "SELECT COUNT(DISTINCT waybill_no) FROM shipments "
                     "WHERE TRIM(REPLACE(status, ';', '')) = '已签收'"),
    ("行注释在末尾", "SELECT 1 -- 这是注释"),
    ("块注释在末尾", "SELECT 1 /* 注释 */"),
    ("双引号标识符", 'SELECT "col;name" FROM "my;table"'),
    ("反引号标识符", "SELECT `col` FROM `tbl`"),
    ("子查询 3 层", "SELECT * FROM (SELECT * FROM (SELECT 1) a) b"),
]


# ── BLOCK：危险语句，必须拦截 ─────────────────────────────────

BLOCK_CASES = [
    ("DROP", "DROP TABLE orders"),
    ("DELETE", "DELETE FROM orders WHERE 1=1"),
    ("TRUNCATE", "TRUNCATE TABLE orders"),
    ("UPDATE", "UPDATE orders SET city = 'x'"),
    ("INSERT", "INSERT INTO orders VALUES (1)"),
    ("ALTER", "ALTER TABLE orders ADD COLUMN x INT"),
    ("GRANT", "GRANT ALL ON *.* TO 'u'@'%'"),
    ("存储过程 xp_", "SELECT * FROM t; xp_cmdshell('rm -rf /')"),
    ("堆叠语句", "SELECT 1; DROP TABLE orders"),
    ("堆叠语句(无空格)", "SELECT 1;DELETE FROM orders"),
    ("注释隐藏堆叠", "SELECT 1 -- c\n; DROP TABLE orders"),
    ("块注释隐藏堆叠", "SELECT 1 /* x */ ; DROP TABLE orders"),
    ("非 SELECT 开头", "PRAGMA table_info(orders)"),
    ("SET 语句", "SET GLOBAL max_connections = 10000"),
    ("ATTACH(duckdb)", "ATTACH '/etc/passwd' AS p"),
    ("COPY 读文件", "COPY t FROM '/etc/passwd'"),
    ("未闭合字面量", "SELECT * FROM t WHERE a = 'abc"),
    # ↓ 以 WITH 开头，能过白名单，只能靠 DELETE/UPDATE 兜底
    ("PG 数据修改 CTE", "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d"),
    ("MySQL REPLACE INTO", "REPLACE INTO orders VALUES (1)"),
    ("MySQL 写文件", "SELECT * FROM t INTO OUTFILE '/tmp/x'"),
    ("MySQL 读文件", "SELECT LOAD_FILE('/etc/passwd')"),
    ("DuckDB 读本地文件", "SELECT * FROM read_csv('/etc/passwd')"),
    ("DuckDB glob 列目录", "SELECT * FROM glob('/etc/*')"),
    ("DoS 休眠函数", "SELECT pg_sleep(100)"),
    ("子查询过深", "SELECT * FROM (SELECT * FROM (SELECT * FROM (SELECT * FROM "
                   "(SELECT * FROM (SELECT * FROM (SELECT 1) a) b) c) d) e) f"),
]


def _run() -> int:
    v = SQLValidator()
    failed = 0

    print("=" * 70)
    print("PASS 组：正常查询必须放行")
    print("=" * 70)
    for name, sql in PASS_CASES:
        ok, reason = v.validate(sql)
        status = "  OK " if ok else "FAIL "
        if not ok:
            failed += 1
        print(f"[{status}] {name:<22} {reason or ''}")

    print()
    print("=" * 70)
    print("BLOCK 组：危险语句必须拦截")
    print("=" * 70)
    for name, sql in BLOCK_CASES:
        ok, reason = v.validate(sql)
        status = "  OK " if not ok else "FAIL "
        if ok:
            failed += 1
        print(f"[{status}] {name:<22} {reason[:56]}")

    # ── enforce_limit ──
    print()
    print("=" * 70)
    print("enforce_limit：只在顶层判断 LIMIT")
    print("=" * 70)
    limit_cases = [
        ("顶层无 LIMIT -> 追加", "SELECT * FROM orders", True),
        ("顶层有 LIMIT -> 不加", "SELECT * FROM orders LIMIT 10", False),
        ("仅子查询有 LIMIT -> 仍追加", "SELECT * FROM (SELECT * FROM t LIMIT 3) x", True),
        ("字符串含 limit 单词 -> 仍追加", "SELECT * FROM t WHERE name = 'limit'", True),
        ("顶层 LIMIT + 子查询 LIMIT -> 不加",
         "SELECT * FROM (SELECT * FROM t LIMIT 3) x LIMIT 5", False),
    ]
    for name, sql, should_append in limit_cases:
        out = v.enforce_limit(sql, limit=1000)
        appended = out != sql.strip().rstrip(";").rstrip()
        good = appended == should_append
        if not good:
            failed += 1
        print(f"[{'  OK ' if good else 'FAIL '}] {name:<32} -> {out[-40:]}")

    # ── sanitize_identifier ──
    print()
    print("=" * 70)
    print("sanitize_identifier：标识符注入防护")
    print("=" * 70)
    id_cases = [
        ("orders", True),
        ("orders_2024", True),
        ("orders; DROP TABLE users", False),
        ("orders--", False),
        ("1orders", False),
        ("", False),
    ]
    for name, should_pass in id_cases:
        try:
            SQLValidator.sanitize_identifier(name)
            passed = True
            err = ""
        except ValueError as e:
            passed = False
            err = str(e)
        good = passed == should_pass
        if not good:
            failed += 1
        print(f"[{'  OK ' if good else 'FAIL '}] {name!r:<32} {err[:40]}")

    print()
    print("=" * 70)
    print(f"结果: {'全部通过' if failed == 0 else f'{failed} 项失败'}")
    print("=" * 70)
    return failed


# pytest 入口
def test_all():
    assert _run() == 0


if __name__ == "__main__":
    sys.exit(0 if _run() == 0 else 1)
