"""Query execution guard — timeout, cancellation, concurrency, row cap.

为什么需要这个模块
────────────────────
SQL 校验器只能拦「非法」语句，拦不住「合法但昂贵」的查询：
一条笛卡尔积、一次全表聚合、一个没有 LIMIT 的大结果集，
语法完全正确、权限也合法，但能打满 CPU 或撑爆内存。

所以执行层必须自带四道闸：

1. 超时       —— 超过 N 秒必须停
2. 真实取消   —— 停了不能只是"不等它"，得让它真的别跑了
3. 并发上限   —— 同时最多 N 个查询
4. 行数上限   —— 结果集超过 N 行截断

其中 (2) 最容易做错：`asyncio.wait_for` 取消的只是 Future，
**线程里阻塞执行的驱动调用根本不会被打断**，查询仍在数据库里跑，
只是调用方不等了。要真取消，必须调用驱动自己的中断接口
（DuckDB 的 `conn.interrupt()`、asyncpg 的 `conn.terminate()` 等）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger("chatsql")


class QueryTimeoutError(TimeoutError):
    """查询超过时限。

    单独定义而不是直接用 asyncio.TimeoutError，是为了让上层能
    区分「用户 SQL 太慢」和「服务内部超时」，给出不同的提示。
    """

    def __init__(self, seconds: float, sql: str = ""):
        self.seconds = seconds
        self.sql = sql
        preview = sql.strip().replace("\n", " ")[:80]
        super().__init__(f"查询超时（>{seconds}s）：{preview}")


class QueryConcurrencyError(RuntimeError):
    """并发查询数达到上限。"""


def _settings_or(default: float, attr: str) -> Any:
    """读配置，失败时回落默认值。

    配置读取本身不该成为执行链路的故障点。
    """
    try:
        from app.config import get_settings
        return getattr(get_settings(), attr)
    except Exception:  # noqa: BLE001
        return default


def query_timeout() -> float:
    """查询超时秒数。"""
    return float(_settings_or(30.0, "query_timeout_seconds") or 30.0)


def max_rows() -> int:
    """结果集最大行数。"""
    return int(_settings_or(10_000, "query_max_rows") or 10_000)


def max_concurrency() -> int:
    """最大并发查询数。"""
    return int(_settings_or(8, "query_max_concurrency") or 8)


async def run_async(
    factory: Callable[[], Awaitable[Any]],
    *,
    timeout: float | None = None,
    sql: str = "",
    on_cancel: Callable[[], Any] | None = None,
) -> Any:
    """执行异步驱动查询，超时则取消并回调清理。

    Args:
        factory: 返回 awaitable 的工厂（每次调用重新发起查询）
        timeout: 超时秒数，None 表示用全局配置
        on_cancel: 超时后的清理动作（终止连接等）
    """
    timeout = timeout if timeout is not None else query_timeout()
    try:
        return await asyncio.wait_for(factory(), timeout)
    except asyncio.TimeoutError:
        _safe_cancel(on_cancel)
        raise QueryTimeoutError(timeout, sql) from None


async def run_blocking(
    fn: Callable[[], Any],
    *,
    timeout: float | None = None,
    sql: str = "",
    on_cancel: Callable[[], Any] | None = None,
) -> Any:
    """在线程池里执行阻塞驱动查询，超时则调用驱动的中断接口。

    关键点：`asyncio.wait_for` 取消不了 executor 线程里已经在跑的
    C 调用。所以超时后必须额外执行 `on_cancel`（如 DuckDB 的
    `conn.interrupt()`），否则 CPU 会一直被这条查询占着。

    Args:
        fn: 阻塞的查询函数
        on_cancel: 中断接口，应当幂等且线程安全
    """
    timeout = timeout if timeout is not None else query_timeout()
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, fn)
    try:
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        _safe_cancel(on_cancel)
        raise QueryTimeoutError(timeout, sql) from None


def _safe_cancel(on_cancel: Callable[[], Any] | None) -> None:
    """执行中断回调，且绝不因清理失败掩盖原本的超时错误。"""
    if on_cancel is None:
        return
    try:
        on_cancel()
    except Exception as e:  # noqa: BLE001
        logger.warning("查询超时后的取消动作失败（查询可能仍在运行）: %s", e)


class ConcurrencyLimiter:
    """全局并发查询限流。

    信号量必须绑定到当前的 event loop，因此惰性创建并在 loop
    变化时重建（测试里每个 asyncio.run 都是新 loop）。
    """

    def __init__(self) -> None:
        self._sem: asyncio.Semaphore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._sem is None or self._loop is not loop:
            self._sem = asyncio.Semaphore(max_concurrency())
            self._loop = loop
        return self._sem

    @property
    def limit(self) -> int:
        return max_concurrency()

    async def __aenter__(self):
        await self._get().acquire()

    async def __aexit__(self, *exc):
        self._get().release()


_limiter = ConcurrencyLimiter()


def get_limiter() -> ConcurrencyLimiter:
    return _limiter


def cap_rows(result: dict[str, Any], limit: int | None = None) -> dict[str, Any]:
    """截断结果集，并标注被截断。

    截断而不是报错：用户问「有多少单」时返回一万行也没法看，
    但明确标注截断行数，避免有人拿它当全量结果做决策。
    """
    limit = limit if limit is not None else max_rows()
    rows = result.get("rows") or []
    if len(rows) <= limit:
        result.setdefault("row_count", len(rows))
        return result

    result["rows"] = rows[:limit]
    result["row_count"] = len(rows)
    result["truncated"] = True
    result["truncated_at"] = limit
    return result
