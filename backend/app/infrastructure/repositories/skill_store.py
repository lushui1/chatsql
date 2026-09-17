"""Skill repository — CRUD operations for skills and execution logs."""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.models import Skill as SkillModel, SkillExecutionLog as LogModel
from app.domain.skill_domain import Skill, SkillExecutionLog, SkillSecurity


def _new_id() -> str:
    return f"skill_{secrets.token_hex(16)}"


def _new_log_id() -> str:
    return f"log_{secrets.token_hex(16)}"


# ── Conversions ──


def _to_domain(model: SkillModel) -> Skill:
    return Skill(
        id=model.id,
        name=model.name,
        version=model.version or "1.0",
        description=model.description or "",
        enabled=model.enabled,
        function_schema=json.loads(model.function_schema) if model.function_schema else {},
        execution_type=model.execution_type or "code",
        code=model.code or "",
        script=model.script or "",
        url=model.url or "",
        security=SkillSecurity(**json.loads(model.security_json)) if model.security_json else SkillSecurity(),
        created_by=model.created_by or "",
        created_at=model.created_at or 0,
        updated_at=model.updated_at or 0,
        tags=json.loads(model.tags) if model.tags else [],
        category=model.category or "",
        call_count=model.call_count or 0,
        last_used_at=model.last_used_at,
    )


def _to_log_domain(model: LogModel) -> SkillExecutionLog:
    return SkillExecutionLog(
        id=model.id,
        skill_id=model.skill_id,
        session_id=model.session_id,
        response_id=model.response_id,
        status=model.status,
        input_args=json.loads(model.input_args) if model.input_args else {},
        output=json.loads(model.output_json) if model.output_json else None,
        error=model.error or "",
        duration_ms=model.duration_ms or 0,
        created_at=model.created_at or 0,
    )


# ── CRUD ──


async def create_skill(db: AsyncSession, skill: Skill) -> Skill:
    now = int(time.time())
    model = SkillModel(
        id=skill.id or _new_id(),
        name=skill.name,
        version=skill.version,
        description=skill.description,
        enabled=skill.enabled,
        function_schema=json.dumps(skill.function_schema, ensure_ascii=False),
        execution_type=skill.execution_type,
        code=skill.code,
        script=skill.script,
        url=skill.url,
        security_json=json.dumps(skill.security.model_dump(), ensure_ascii=False),
        created_by=skill.created_by,
        tags=json.dumps(skill.tags, ensure_ascii=False),
        category=skill.category,
        created_at=now,
        updated_at=now,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return _to_domain(model)


async def get_skill(db: AsyncSession, skill_id: str) -> Skill | None:
    result = await db.execute(select(SkillModel).where(SkillModel.id == skill_id))
    model = result.scalar_one_or_none()
    return _to_domain(model) if model else None


async def get_skill_by_name(db: AsyncSession, name: str) -> Skill | None:
    result = await db.execute(select(SkillModel).where(SkillModel.name == name))
    model = result.scalar_one_or_none()
    return _to_domain(model) if model else None


async def list_skills(db: AsyncSession, *, enabled_only: bool = True, category: str | None = None) -> list[Skill]:
    stmt = select(SkillModel)
    if enabled_only:
        stmt = stmt.where(SkillModel.enabled == True)
    if category:
        stmt = stmt.where(SkillModel.category == category)
    stmt = stmt.order_by(SkillModel.updated_at.desc())
    result = await db.execute(stmt)
    return [_to_domain(m) for m in result.scalars().all()]


async def update_skill(db: AsyncSession, skill_id: str, updates: dict[str, Any]) -> Skill | None:
    stmt = (
        update(SkillModel)
        .where(SkillModel.id == skill_id)
        .values(updated_at=int(time.time()), **updates)
        .returning(SkillModel)
    )
    result = await db.execute(stmt)
    await db.commit()
    model = result.scalar_one_or_none()
    return _to_domain(model) if model else None


async def delete_skill(db: AsyncSession, skill_id: str) -> bool:
    stmt = delete(SkillModel).where(SkillModel.id == skill_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def toggle_skill(db: AsyncSession, skill_id: str, enabled: bool) -> Skill | None:
    return await update_skill(db, skill_id, {"enabled": enabled})


async def increment_call_count(db: AsyncSession, skill_id: str) -> None:
    await db.execute(
        update(SkillModel)
        .where(SkillModel.id == skill_id)
        .values(
            call_count=SkillModel.call_count + 1,
            last_used_at=int(time.time()),
        )
    )
    await db.commit()


# ── Execution Logs ──


async def create_execution_log(db: AsyncSession, log: SkillExecutionLog) -> SkillExecutionLog:
    model = LogModel(
        id=log.id or _new_log_id(),
        skill_id=log.skill_id,
        session_id=log.session_id,
        response_id=log.response_id,
        status=log.status,
        input_args=json.dumps(log.input_args, ensure_ascii=False),
        output_json=json.dumps(log.output, ensure_ascii=False) if log.output else None,
        error=log.error,
        duration_ms=log.duration_ms,
        created_at=log.created_at or int(time.time()),
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return _to_log_domain(model)


async def list_execution_logs(
    db: AsyncSession,
    *,
    skill_id: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
) -> list[SkillExecutionLog]:
    stmt = select(LogModel)
    if skill_id:
        stmt = stmt.where(LogModel.skill_id == skill_id)
    if session_id:
        stmt = stmt.where(LogModel.session_id == session_id)
    stmt = stmt.order_by(LogModel.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return [_to_log_domain(m) for m in result.scalars().all()]
