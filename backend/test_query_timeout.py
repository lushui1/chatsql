"""Query execution guard tests — timeout / cancellation / concurrency / row cap.

这些用例针对的是「合法但昂贵」的查询：语法正确、权限合法，
但能打满 CPU 或撑爆内存 —— SQL 校验器拦不住，只能靠执行层的闸门。
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

passed = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"[  OK ] {name}  {detail}")
    else:
        failed += 1
        print(f"[FAIL ] {name}  {detail}")


def section(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


# 把超时压到 2 秒，否则测一次慢查询要等 30 秒。
# 必须清 lru_cache，否则拿到的是先前构建好的 Settings。
import os  # noqa: E402

os.environ["CHATSQL_QUERY_TIMEOUT_SECONDS"] = "2"
from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.application.datasources import (  # noqa: E402
    DataSourceConfig,
    DuckDBDataSource,
)
from app.application.datasources.query_guard import (  # noqa: E402
    QueryTimeoutError,
    cap_rows,
    get_limiter,
    query_timeout,
    run_async,
    run_blocking,
)


# DuckDB 里一条能稳定跑很久的查询：递归 CTE 做无意义的膨胀
# 慢，但内存 O(1)：递归 CTE 只做计数，不物化中间结果。
# 若改成自连接笛卡尔积，测试机可能先 OOM 而不是先超时。
SLOW_SQL = """
WITH RECURSIVE x AS (
    SELECT 1 AS n
    UNION ALL
    SELECT n + 1 FROM x WHERE n < 500000000
)
SELECT COUNT(*) FROM x
"""


async def main() -> None:
    # ── 1. 阻塞查询超时：必须抛 QueryTimeoutError ──
    section("1. DuckDB 慢查询超时")
    ds = DuckDBDataSource(":memory:", "main")
    t0 = time.time()
    raised = False
    try:
        await ds.execute(SLOW_SQL)
    except QueryTimeoutError as e:
        raised = True
        detail = f"{time.time() - t0:.1f}s 后超时（配置 {query_timeout()}s）"
        check("慢查询触发超时", True, detail)
        # 错误信息里要能看到 SQL，方便排查
        check("错误信息含 SQL 摘要", "COUNT" in str(e) or "查询超时" in str(e))
    except Exception as e:  # noqa: BLE001
        check("慢查询触发超时", False, f"抛了 {type(e).__name__}: {str(e)[:80]}")
    else:
        check("慢查询触发超时", False, "居然跑完了")
    check("确实抛了 QueryTimeoutError", raised)

    # ── 2. 超时后连接仍可用（interrupt 不能把连接打废）──
    section("2. 超时中断后数据源仍可继续查询")
    try:
        r = await ds.execute("SELECT 1 AS ok")
        check("中断后新查询正常", r["rows"][0]["ok"] == 1, f"rows={r['rows']}")
    except Exception as e:  # noqa: BLE001
        check("中断后新查询正常", False, f"{type(e).__name__}: {str(e)[:100]}")

    # ── 3. 正常查询不受影响 ──
    section("3. 正常查询不受闸门影响")
    r = await ds.execute("SELECT * FROM sort_center ORDER BY volume DESC")
    check("正常查询返回结果", len(r["rows"]) == 5, f"{len(r['rows'])} 行")
    check("未被误截断", "truncated" not in r)

    # ── 4. run_blocking 的取消回调确实被调用 ──
    section("4. 超时后取消回调被执行（不是只抛异常）")
    cancelled = {"n": 0}

    def _slow():
        time.sleep(5)
        return "done"

    def _cancel():
        cancelled["n"] += 1

    try:
        await run_blocking(_slow, timeout=0.3, sql="sleep", on_cancel=_cancel)
    except QueryTimeoutError:
        pass
    check("取消回调被调用", cancelled["n"] == 1, f"调用 {cancelled['n']} 次")

    # 取消回调自己抛异常时，不能掩盖超时错误
    def _bad_cancel():
        raise RuntimeError("cancel failed")

    err_type = None
    try:
        await run_blocking(_slow, timeout=0.3, on_cancel=_bad_cancel)
    except QueryTimeoutError:
        err_type = "QueryTimeoutError"
    except Exception as e:  # noqa: BLE001
        err_type = type(e).__name__
    check("取消回调异常不掩盖超时", err_type == "QueryTimeoutError", f"实际 {err_type}")

    # ── 5. 异步路径 run_async ──
    section("5. 异步查询超时")
    async def _slow_async():
        await asyncio.sleep(5)
        return "done"

    t0 = time.time()
    try:
        await run_async(_slow_async, timeout=0.3, sql="SELECT slow")
        check("异步超时生效", False, "没超时")
    except QueryTimeoutError:
        check("异步超时生效", True, f"{time.time() - t0:.1f}s")

    async def _fast_async():
        return "ok"

    check("异步正常不受影响", await run_async(_fast_async, timeout=5) == "ok")

    # ── 6. 行数上限 ──
    section("6. 结果集行数截断")
    big = {"rows": [{"i": i} for i in range(500)], "columns": [{"name": "i"}]}
    capped = cap_rows(dict(big), limit=100)
    check("超限时截断", len(capped["rows"]) == 100, f"{len(capped['rows'])} 行")
    check("标注 truncated", capped.get("truncated") is True)
    check("保留真实总行数", capped.get("row_count") == 500, f"row_count={capped.get('row_count')}")

    small = {"rows": [{"i": i} for i in range(10)], "columns": []}
    out = cap_rows(dict(small), limit=100)
    check("未超限不截断", len(out["rows"]) == 10 and "truncated" not in out)

    # ── 6b. 非 JSON 原生类型必须能序列化 ──
    section("6b. DB 类型转换（DECIMAL / 日期 / bytes）")
    import datetime as _dt
    import json as _json
    from decimal import Decimal as _D

    from app.application.datasources.query_guard import (
        cap_rows as _cap,
    )

    weird = {
        "columns": [{"name": "v"}],
        "rows": [
            {"v": _D("12.34")},                    # DECIMAL —— 最常见
            {"v": _D("0.000000000000000001")},     # 极小值
            {"v": _dt.date(2025, 6, 1)},
            {"v": _dt.datetime(2025, 6, 1, 12, 30)},
            {"v": _dt.timedelta(hours=3)},
            {"v": b"binary"},
            {"v": None},
        ],
    }
    out = _cap(dict(weird), limit=100)
    try:
        s = _json.dumps(out, ensure_ascii=False)
        check("含 DECIMAL 的结果可 JSON 序列化", True, f"{len(s)} 字符")
    except TypeError as e:
        check("含 DECIMAL 的结果可 JSON 序列化", False, str(e))
    check("DECIMAL → float 保住数值语义", out["rows"][0]["v"] == 12.34,
          f"实际 {out['rows'][0]['v']!r}")
    check("日期 → ISO 字符串", out["rows"][2]["v"] == "2025-06-01")
    check("timedelta → 秒", out["rows"][4]["v"] == 10800.0)
    check("bytes → 文本", out["rows"][5]["v"] == "binary")

    # 真实 DuckDB 上的 DECIMAL 查询（端到端，最容易炸的组合）
    from app.application.datasources.manager import get_manager

    mgr = get_manager()
    if not mgr.has_source("demo"):
        mgr.add_source(DataSourceConfig(name="demo", type="duckdb", url=":memory:"))

    r_dec = await mgr.execute(
        "demo", "SELECT CAST(1 AS DECIMAL(18,2)) AS amount, 'x' AS tag"
    )
    try:
        _json.dumps(r_dec, ensure_ascii=False)
        check("DuckDB DECIMAL 端到端可序列化", True, f"amount={r_dec['rows'][0]['amount']!r}")
    except TypeError as e:
        check("DuckDB DECIMAL 端到端可序列化", False, str(e))

    # ── 7. 并发上限 ──
    section("7. 并发查询限流")
    lim = get_limiter()
    limit_n = lim.limit
    running = {"cur": 0, "peak": 0}

    async def _one():
        async with lim:
            running["cur"] += 1
            running["peak"] = max(running["peak"], running["cur"])
            await asyncio.sleep(0.15)
            running["cur"] -= 1

    t0 = time.time()
    await asyncio.gather(*[_one() for _ in range(limit_n * 2)])
    elapsed = time.time() - t0
    check("并发不超过上限", running["peak"] <= limit_n,
          f"峰值 {running['peak']} / 上限 {limit_n}")
    check("确实发生了排队", elapsed >= 0.28, f"耗时 {elapsed:.2f}s（未排队应 ~0.15s）")

    # ── 8. 经 manager 出口：并发 + 截断 + 校验 全部生效 ──
    section("8. manager.execute 统一出口")
    from app.application.datasources.manager import get_manager

    mgr = get_manager()
    if not mgr.has_source("demo"):
        mgr.add_source(DataSourceConfig(name="demo", type="duckdb", url=":memory:"))

    r = await mgr.execute("demo", "SELECT * FROM orders")
    check("出口返回 row_count", "row_count" in r, f"row_count={r.get('row_count')}")
    check("出口未误截断小结果", not r.get("truncated"))

    try:
        await mgr.execute("demo", "DROP TABLE orders")
        check("出口仍拦截危险语句", False, "没拦住")
    except ValueError as e:
        check("出口仍拦截危险语句", True, str(e)[:60])

    # ── 汇总 ──
    print()
    print("=" * 70)
    if failed == 0:
        print(f"结果: 全部通过（{passed} 项）")
    else:
        print(f"结果: {failed} 项失败 / 共 {passed + failed} 项")
    print("=" * 70)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
