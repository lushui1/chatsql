"""LLM 重试 / 退避 的单元测试。

重点验证两条安全性质：
1. 建连阶段失败（429/5xx/超时）→ 自动退避重试
2. **已经吐出内容后失败 → 绝不重试**（否则前端会收到重复文本）

运行： python backend/test_llm_retry.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.application.llm import _is_retryable, _retry_stream  # noqa: E402

PASS, FAIL = "  OK ", "FAIL "
failed = 0


class FakeError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RateLimitError(FakeError):
    pass


def _make_stream(chunks: list[str], fail_after: int | None = None,
                 fail_exc: BaseException | None = None):
    """构造一个可控的流式数据源。

    Args:
        chunks: 要吐出的内容
        fail_after: 吐出第 N 个 chunk 后抛异常（None = 不抛）
        fail_exc: 要抛的异常
    """
    async def _stream():
        for i, c in enumerate(chunks):
            if fail_after is not None and i == fail_after:
                raise fail_exc or RuntimeError("boom")
            yield c
    return _stream


async def _collect(agen) -> list[str]:
    return [c async for c in agen]


async def main() -> int:
    global failed
    import app.application.llm as llm

    # 测试期间把退避时间压到 0，避免跑得慢
    llm.RETRY_DELAYS = [0, 0, 0]

    print("=" * 70)
    print("1. 建连阶段失败 → 应重试并最终成功")
    print("=" * 70)
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError("rate limit exceeded", status_code=429)
        return _make_stream(["a", "b", "c"])()

    got = await _collect(_retry_stream(factory))
    ok = got == ["a", "b", "c"] and calls["n"] == 3
    if not ok:
        failed += 1
    print(f"[{PASS if ok else FAIL}] 前2次429第3次成功  调用次数={calls['n']} 结果={got}")

    print()
    print("=" * 70)
    print("2. 已吐出内容后失败 → 绝不重试（防止前端收到重复文本）")
    print("=" * 70)
    calls2 = {"n": 0}

    async def factory2():
        calls2["n"] += 1
        # 吐出 x、y 之后在第 3 个 chunk 处挂掉（fail_after=2 指在 index 2 抛）
        return _make_stream(["x", "y", "z"], fail_after=2,
                            fail_exc=RuntimeError("mid-stream failure"))()

    raised = None
    got2 = []
    try:
        async for c in _retry_stream(factory2):
            got2.append(c)
    except RuntimeError as e:
        raised = e

    ok = calls2["n"] == 1 and got2 == ["x", "y"] and raised is not None
    if not ok:
        failed += 1
    print(f"[{PASS if ok else FAIL}] 中途失败不重试      调用次数={calls2['n']} "
          f"已收={got2} 抛出={type(raised).__name__ if raised else None}")

    print()
    print("=" * 70)
    print("3. 不可重试错误（400）→ 立即失败，不浪费重试次数")
    print("=" * 70)
    calls3 = {"n": 0}

    async def factory3():
        calls3["n"] += 1
        raise FakeError("bad request", status_code=400)

    try:
        await _collect(_retry_stream(factory3))
        ok = False
    except FakeError:
        ok = calls3["n"] == 1
    if not ok:
        failed += 1
    print(f"[{PASS if ok else FAIL}] 400 不重试          调用次数={calls3['n']}")

    print()
    print("=" * 70)
    print("4. 重试耗尽 → 抛出最后一次异常")
    print("=" * 70)
    calls4 = {"n": 0}

    async def factory4():
        calls4["n"] += 1
        raise RateLimitError("still rate limited", status_code=429)

    try:
        await _collect(_retry_stream(factory4))
        ok = False
    except RateLimitError:
        ok = calls4["n"] == llm.RETRY_MAX + 1
    if not ok:
        failed += 1
    print(f"[{PASS if ok else FAIL}] 重试耗尽后抛出      调用次数={calls4['n']} "
          f"(期望 {llm.RETRY_MAX + 1})")

    print()
    print("=" * 70)
    print("5. _is_retryable 判定")
    print("=" * 70)
    cases = [
        ("429 状态码", FakeError("x", 429), True),
        ("503 状态码", FakeError("x", 503), True),
        ("400 状态码", FakeError("x", 400), False),
        ("401 状态码", FakeError("x", 401), False),
        ("RateLimitError 类名", RateLimitError("x"), True),
        ("超时文案", RuntimeError("request timed out"), True),
        ("普通错误", RuntimeError("something broke"), False),
    ]
    for name, exc, expect in cases:
        got = _is_retryable(exc)
        good = got == expect
        if not good:
            failed += 1
        print(f"[{PASS if good else FAIL}] {name:<20} retryable={got}")

    print()
    print("=" * 70)
    print(f"结果: {'全部通过' if failed == 0 else f'{failed} 项失败'}")
    print("=" * 70)
    return failed


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) == 0 else 1)
