"""LearnService — 从对话中提取套路、检索、注入。

核心职责：
1. extract_from_response — 从对话中提取可复用套路
2. retrieve — 根据用户问题检索相关套路
3. build_learn_context — 构建注入 system prompt 的学习上下文
4. record_hit — 记录套路被命中
5. 治理 — CRUD + 评分
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import secrets
import time
from typing import Any

from sqlalchemy import select, update, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.infrastructure.models import LearnedRoutine, LearnObservation, LearnAudit
from app.application.learn.distiller import ResponseDistiller

logger = logging.getLogger("chatsql.learn")


def _fingerprint(question: str) -> str:
    """计算问题指纹（用于去重）。"""
    normalized = question.strip().lower()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def _now() -> int:
    return int(time.time())


def _new_id(prefix: str = "routine") -> str:
    return f"{prefix}_{secrets.token_hex(16)}"


def _freshness_decay(created_at: int) -> float:
    """新鲜度衰减：7天内=1.0, 30天=0.8, 90天=0.5, 更久=0.3"""
    age_days = (_now() - created_at) / 86400
    if age_days <= 7:
        return 1.0
    elif age_days <= 30:
        return 0.8
    elif age_days <= 90:
        return 0.5
    return 0.3


class LearnService:
    """学习服务 — 从对话中提取套路、检索、注入。"""

    def __init__(self, db: AsyncSession, settings: Settings):
        self._db = db
        self._settings = settings
        self._distiller = ResponseDistiller(settings)

    # ── 提取 ──

    async def extract_from_response(
        self,
        session_id: str,
        response_id: str,
        user_q: str,
        assistant_output: str,
    ) -> list[LearnedRoutine]:
        """从一次对话响应中提取可复用套路。"""
        # 1. 判断是否值得学习
        should = await self._distiller.should_learn(user_q, assistant_output)
        if not should:
            logger.debug(f"跳过学习: session={session_id}, resp={response_id}")
            return []

        # 2. 检查去重
        fp = _fingerprint(user_q)
        existing = await self._db.execute(
            select(LearnedRoutine).where(
                LearnedRoutine.question_fingerprint == fp,
                LearnedRoutine.status.in_(["candidate", "active"]),
            )
        )
        if existing.scalar_one_or_none():
            logger.debug(f"套路已存在，跳过: fp={fp}")
            return []

        # 3. 提取套路
        extracted = await self._distiller.extract_routine(user_q, assistant_output)
        if not extracted:
            return []

        # 4. 写入数据库
        routine_id = _new_id()
        now = _now()
        routine = LearnedRoutine(
            id=routine_id,
            status="candidate",
            title=extracted["title"],
            summary=extracted["summary"],
            routine_type=extracted["routine_type"],
            content=extracted["content"],
            question_fingerprint=fp,
            source_session_id=session_id,
            source_response_id=response_id,
            confidence=0.5,
            reuse_count=0,
            created_at=now,
            updated_at=now,
            tags=json.dumps(extracted.get("tags", []), ensure_ascii=False),
        )
        self._db.add(routine)

        # 5. 写入观测记录
        observation = LearnObservation(
            id=_new_id("obs"),
            routine_id=routine_id,
            session_id=session_id,
            response_id=response_id,
            event_type="created",
            score_delta=0.0,
            created_at=now,
        )
        self._db.add(observation)

        # 6. 写入审计
        audit = LearnAudit(
            id=_new_id("audit"),
            routine_id=routine_id,
            action="created",
            detail=f"从 session={session_id}, resp={response_id} 提取",
            created_at=now,
        )
        self._db.add(audit)

        await self._db.commit()
        logger.info(f"提取套路: id={routine_id}, title={extracted['title']}")
        return [routine]

    # ── 检索 ──

    async def retrieve(self, query: str, top_k: int = 5) -> list[LearnedRoutine]:
        """根据用户问题检索相关套路。"""
        fp = _fingerprint(query)

        # 1. 先精确匹配 fingerprint（仅 active 状态）
        exact = await self._db.execute(
            select(LearnedRoutine).where(
                LearnedRoutine.question_fingerprint == fp,
                LearnedRoutine.status == "active",
            )
        )
        exact_match = exact.scalar_one_or_none()
        if exact_match:
            return [exact_match]

        # 2. 按状态匹配所有 active 套路，按评分排序
        result = await self._db.execute(
            select(LearnedRoutine).where(
                LearnedRoutine.status == "active",
            )
        )
        routines = list(result.scalars().all())

        if not routines:
            return []

        # 3. 简单关键词匹配（基于 tags 和 title）
        query_lower = query.lower()
        scored: list[tuple[float, LearnedRoutine]] = []
        for r in routines:
            # 基础分
            base_score = r.confidence * (1 + math.log(r.reuse_count + 1))
            base_score *= _freshness_decay(r.created_at)

            # 关键词加成
            tags = json.loads(r.tags) if r.tags else []
            tag_match = any(t.lower() in query_lower for t in tags)
            title_match = (r.title or "").lower() in query_lower or query_lower in (r.title or "").lower()
            if tag_match or title_match:
                base_score *= 2.0

            scored.append((base_score, r))

        # 4. 排序取 top_k
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_k]]

    # ── 注入 ──

    async def build_learn_context(self, query: str) -> str:
        """构建注入到 system prompt 的学习上下文。"""
        routines = await self.retrieve(query)
        if not routines:
            return ""

        lines = ["## 历史学习到的分析套路\n"]
        for r in routines:
            tags = json.loads(r.tags) if r.tags else []
            lines.append(f"### {r.title}\n{r.summary}\n适用场景: {', '.join(tags)}\n")
        return "\n".join(lines)

    # ── 命中记录 ──

    async def record_hit(self, routine_id: str, session_id: str, response_id: str | None = None):
        """记录套路被命中。"""
        now = _now()

        # 更新 reuse_count 和 last_hit_at
        result = await self._db.execute(
            select(LearnedRoutine).where(LearnedRoutine.id == routine_id)
        )
        routine = result.scalar_one_or_none()
        if not routine:
            return

        routine.reuse_count = (routine.reuse_count or 0) + 1
        routine.last_hit_at = now
        routine.updated_at = now

        # 写入观测
        observation = LearnObservation(
            id=_new_id("obs"),
            routine_id=routine_id,
            session_id=session_id,
            response_id=response_id,
            event_type="hit",
            score_delta=0.0,
            created_at=now,
        )
        self._db.add(observation)

        # 审计
        audit = LearnAudit(
            id=_new_id("audit"),
            routine_id=routine_id,
            action="hit",
            detail=f"session={session_id}",
            created_at=now,
        )
        self._db.add(audit)

        await self._db.commit()

    # ── 评分 ──

    def score_routine(self, routine: LearnedRoutine) -> float:
        """计算套路综合得分。"""
        base = routine.confidence * (1 + math.log(routine.reuse_count + 1))
        return base * _freshness_decay(routine.created_at)

    # ── 治理 ──

    async def list_routines(self, status: str | None = None, limit: int = 50) -> list[LearnedRoutine]:
        """列出套路。"""
        query = select(LearnedRoutine)
        if status:
            query = query.where(LearnedRoutine.status == status)
        query = query.order_by(desc(LearnedRoutine.created_at)).limit(limit)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def get_routine(self, routine_id: str) -> LearnedRoutine | None:
        """获取套路详情。"""
        result = await self._db.execute(
            select(LearnedRoutine).where(LearnedRoutine.id == routine_id)
        )
        return result.scalar_one_or_none()

    async def update_routine_status(self, routine_id: str, new_status: str) -> LearnedRoutine | None:
        """更新套路状态。"""
        result = await self._db.execute(
            select(LearnedRoutine).where(LearnedRoutine.id == routine_id)
        )
        routine = result.scalar_one_or_none()
        if not routine:
            return None

        old_status = routine.status
        routine.status = new_status
        routine.updated_at = _now()

        # 审计
        audit = LearnAudit(
            id=_new_id("audit"),
            routine_id=routine_id,
            action=new_status,
            detail=f"状态变更: {old_status} → {new_status}",
            created_at=_now(),
        )
        self._db.add(audit)

        await self._db.commit()
        await self._db.refresh(routine)
        return routine

    async def delete_routine(self, routine_id: str) -> bool:
        """删除套路。"""
        result = await self._db.execute(
            select(LearnedRoutine).where(LearnedRoutine.id == routine_id)
        )
        routine = result.scalar_one_or_none()
        if not routine:
            return False

        await self._db.delete(routine)
        await self._db.commit()
        return True

    async def get_stats(self) -> dict[str, Any]:
        """获取学习统计。"""
        # 总数
        total = await self._db.execute(select(func.count(LearnedRoutine.id)))
        total_count = total.scalar() or 0

        # 各状态数量
        status_counts: dict[str, int] = {}
        for status in ["candidate", "active", "deprecated", "superseded"]:
            result = await self._db.execute(
                select(func.count(LearnedRoutine.id)).where(LearnedRoutine.status == status)
            )
            status_counts[status] = result.scalar() or 0

        # 命中总数
        hit_result = await self._db.execute(
            select(func.sum(LearnedRoutine.reuse_count))
        )
        total_hits = hit_result.scalar() or 0

        # 最近活跃的套路
        recent = await self._db.execute(
            select(LearnedRoutine)
            .where(LearnedRoutine.status == "active")
            .order_by(desc(LearnedRoutine.last_hit_at))
            .limit(5)
        )
        top_routines = []
        for r in recent.scalars().all():
            top_routines.append({
                "id": r.id,
                "title": r.title,
                "reuse_count": r.reuse_count,
                "score": round(self.score_routine(r), 3),
            })

        return {
            "total_routines": total_count,
            "status_counts": status_counts,
            "total_hits": total_hits,
            "top_routines": top_routines,
        }
