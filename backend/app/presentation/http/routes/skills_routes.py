"""Skills API routes — CRUD and execution."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure import get_db
from app.domain.skill_domain import Skill, SkillExecutionContext, SkillSecurity
from app.application.skills.service import SkillService

router = APIRouter(prefix="/v1/skills")
logger = logging.getLogger("chatsql")


# ── Request Models ──


class SkillCreateRequest(BaseModel):
    name: str
    version: str = "1.0"
    description: str
    function_schema: dict
    execution_type: str  # code | script | http
    code: str = ""
    script: str = ""
    url: str = ""
    security: dict = {}
    category: str = ""
    tags: list[str] = []


class SkillUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    function_schema: dict | None = None
    code: str | None = None
    script: str | None = None
    url: str | None = None
    security: dict | None = None
    enabled: bool | None = None
    category: str | None = None
    tags: list[str] | None = None


class SkillExecuteRequest(BaseModel):
    arguments: dict = {}
    session_id: str = ""
    datasource: str | None = None
    existing_data: dict = {}


async def get_skill_service(db: AsyncSession = Depends(get_db)) -> SkillService:
    return SkillService(db)


# ── CRUD ──


@router.get("")
async def list_skills(
    service: SkillService = Depends(get_skill_service),
    enabled: bool = True,
    category: str | None = None,
) -> list[dict]:
    skills = await service.list_skills(enabled_only=enabled, category=category)
    return [s.model_dump() for s in skills]


@router.post("")
async def create_skill(
    body: SkillCreateRequest,
    service: SkillService = Depends(get_skill_service),
) -> dict:
    # Check uniqueness
    existing = await service.get_skill_by_name(body.name)
    if existing:
        raise HTTPException(status_code=400, detail=f"Skill name '{body.name}' already exists")

    # Validate schema
    if not body.function_schema.get("name"):
        raise HTTPException(status_code=400, detail="function_schema must have 'name'")
    if not body.function_schema.get("description"):
        raise HTTPException(status_code=400, detail="function_schema must have 'description'")

    # Block reserved names
    reserved = {"execute_sql", "planning", "chatsql_chart", "ask_clarification", "propose_subscription"}
    if body.function_schema["name"] in reserved:
        raise HTTPException(status_code=400, detail=f"Skill name '{body.function_schema['name']}' is reserved")
    if body.function_schema["name"].startswith("chatsql_"):
        raise HTTPException(status_code=400, detail="Skill names cannot use 'chatsql_' prefix")

    skill = Skill(
        id=f"skill_{body.name}",
        name=body.name,
        version=body.version,
        description=body.description,
        enabled=True,
        function_schema=body.function_schema,
        execution_type=body.execution_type,
        code=body.code,
        script=body.script,
        url=body.url,
        security=SkillSecurity(**body.security) if body.security else SkillSecurity(),
        category=body.category,
        tags=body.tags,
    )
    created = await service.create_skill(skill)
    return created.model_dump()


@router.get("/{skill_id}")
async def get_skill(
    skill_id: str,
    service: SkillService = Depends(get_skill_service),
) -> dict:
    skill = await service.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill.model_dump()


@router.put("/{skill_id}")
async def update_skill(
    skill_id: str,
    body: SkillUpdateRequest,
    service: SkillService = Depends(get_skill_service),
) -> dict:
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    skill = await service.update_skill(skill_id, updates)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill.model_dump()


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: str,
    service: SkillService = Depends(get_skill_service),
) -> dict:
    deleted = await service.delete_skill(skill_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"deleted": True}


@router.post("/{skill_id}/toggle")
async def toggle_skill(
    skill_id: str,
    body: dict[str, bool],
    service: SkillService = Depends(get_skill_service),
) -> dict:
    enabled = body.get("enabled", False)
    skill = await service.toggle_skill(skill_id, enabled)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill.model_dump()


# ── Execution ──


@router.post("/{skill_id}/execute")
async def execute_skill(
    skill_id: str,
    body: SkillExecuteRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = SkillService(db)
    skill = await service.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not skill.enabled:
        raise HTTPException(status_code=400, detail="Skill is disabled")

    context = SkillExecutionContext(
        skill=skill,
        arguments=body.arguments,
        session_id=body.session_id,
        datasource=body.datasource,
        existing_data=body.existing_data,
    )

    result = await service.execute_skill(context)
    return result


# ── Logs ──


@router.get("/{skill_id}/logs")
async def list_execution_logs(
    skill_id: str,
    session_id: str | None = None,
    limit: int = 50,
    service: SkillService = Depends(get_skill_service),
) -> list[dict]:
    from app.infrastructure.repositories import skill_store as store
    logs = await store.list_execution_logs(skill_id=skill_id, session_id=session_id, limit=limit)
    return [log.model_dump() for log in logs]
