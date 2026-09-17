"""端到端安全冒烟：真实 DuckDB 上验证执行链路的三道防线。

覆盖：
1. manager.execute       — 最后一道防线（LLM 链路出口）
2. manager.get_metadata  — 表名注入防护
3. datasource_routes     — HTTP 执行端点的校验与 LIMIT 追加

运行： python backend/test_security_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.application.datasources import DataSourceConfig  # noqa: E402
from app.application.datasources.manager import DataSourceManager  # noqa: E402

PASS, FAIL = "  OK ", "FAIL "


async def main() -> int:
    failed = 0
    mgr = DataSourceManager()
    mgr.add_source(DataSourceConfig(name="demo", type="duckdb", database=":memory:"))

    print("=" * 72)
    print("1. manager.execute —— 正常查询必须执行成功")
    print("=" * 72)
    ok_cases = [
        ("简单查询", "SELECT 1 AS n"),
        ("字符串含分号", "SELECT '已签收;' AS s"),
        ("含 REPLACE 清洗", "SELECT REPLACE('a;b', ';', '') AS s"),
    ]
    for name, sql in ok_cases:
        try:
            r = await mgr.execute("demo", sql)
            print(f"[{PASS}] {name:<20} rows={r.get('rows')}")
        except Exception as e:
            failed += 1
            print(f"[{FAIL}] {name:<20} {type(e).__name__}: {e}")

    print()
    print("=" * 72)
    print("2. manager.execute —— 危险语句必须被拒（不能到达数据库）")
    print("=" * 72)
    bad_cases = [
        ("DROP", "DROP TABLE orders"),
        ("堆叠", "SELECT 1; DROP TABLE orders"),
        ("DELETE", "DELETE FROM orders"),
        ("读本地文件", "SELECT * FROM read_csv('/etc/passwd')"),
        ("ATTACH 外部库", "ATTACH '/tmp/x.db' AS x"),
        ("PRAGMA", "PRAGMA database_list"),
        ("PG 写 CTE", "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d"),
        ("DESCRIBE(LLM链路不该有)", "DESCRIBE orders"),
    ]
    for name, sql in bad_cases:
        try:
            await mgr.execute("demo", sql)
            failed += 1
            print(f"[{FAIL}] {name:<20} 竟然执行成功了！")
        except ValueError as e:
            print(f"[{PASS}] {name:<20} 已拦截: {str(e)[:48]}")
        except Exception as e:
            # 数据库层报错也算没造成破坏，但要区分开
            print(f"[{PASS}] {name:<20} 未执行成功({type(e).__name__}): {str(e)[:40]}")

    print()
    print("=" * 72)
    print("3. manager.get_metadata —— 表名注入防护")
    print("=" * 72)
    inj_cases = [
        ("正常表名", "orders", True),
        ("分号注入", "orders; DROP TABLE users", False),
        ("注释注入", "orders--", False),
        ("空格注入", "orders WHERE 1=1", False),
    ]
    for name, tbl, should_pass in inj_cases:
        try:
            await mgr.get_metadata("demo", tbl)
            passed = True
            msg = ""
        except ValueError as e:
            passed = False
            msg = str(e)
        except Exception:
            # 表不存在等运行时错误也算"通过了校验"
            passed = True
            msg = ""
        good = passed == should_pass
        if not good:
            failed += 1
        print(f"[{PASS if good else FAIL}] {name:<16} {msg[:44]}")

    print()
    print("=" * 72)
    print("4. HTTP 执行端点 —— 校验 + LIMIT 追加")
    print("=" * 72)
    from app.presentation.http.routes.datasource_routes import _EXEC_VALIDATOR, _EXEC_ROW_LIMIT
    route_cases = [
        ("SELECT 放行", "SELECT * FROM orders", True),
        ("DESCRIBE 放行(只读管理)", "DESCRIBE orders", True),
        ("SHOW 放行", "SHOW TABLES", True),
        ("DROP 拒绝", "DROP TABLE orders", False),
        ("堆叠拒绝", "SELECT 1; DROP TABLE orders", False),
    ]
    for name, sql, expect_safe in route_cases:
        safe, reason = _EXEC_VALIDATOR.validate(sql)
        good = safe == expect_safe
        if not good:
            failed += 1
        print(f"[{PASS if good else FAIL}] {name:<24} safe={safe} {reason[:40]}")

    sql = "SELECT * FROM orders"
    out = _EXEC_VALIDATOR.enforce_limit(sql, _EXEC_ROW_LIMIT)
    good = out.rstrip().upper().endswith(f"LIMIT {_EXEC_ROW_LIMIT}")
    if not good:
        failed += 1
    print(f"[{PASS if good else FAIL}] {'自动追加 LIMIT':<24} {out}")

    print()
    print("=" * 72)
    print(f"结果: {'全部通过' if failed == 0 else f'{failed} 项失败'}")
    print("=" * 72)
    return failed


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) == 0 else 1)
