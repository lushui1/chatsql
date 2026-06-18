"""Learn API routes — 套路管理 + 学习统计。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.infrastructure import get_db
from app.application.learn.service import LearnService
from app.presentation.http.security.auth_utils import verify_api_key

router = APIRouter(prefix="/v1/learn")
_settings = get_settings()


# ── Schemas ──

class RoutineUpdateRequest(BaseModel):
    status: str = Field(..., pattern="^(active|deprecated|superseded)$")


class RoutineResponse(BaseModel):
    id: str
    status: str
    title: str | None = None
    summary: str | None = None
    routine_type: str | None = None
    content: str | None = None
    tags: list[str] = []
    confidence: float = 0.5
    reuse_count: int = 0
    score: float = 0.0
    created_at: int | None = None
    updated_at: int | None = None
    source_session_id: str | None = None


# ── Routes ──

@router.get("/routines")
async def list_routines(
    status: str | None = Query(None, description="按状态过滤: candidate/active/deprecated/superseded"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """查看套路列表。"""
    service = LearnService(db, _settings)
    routines = await service.list_routines(status=status, limit=limit)

    items = []
    for r in routines:
        tags = []
        if r.tags:
            import json
            try:
                tags = json.loads(r.tags)
            except Exception:
                pass
        items.append({
            "id": r.id,
            "status": r.status,
            "title": r.title,
            "summary": r.summary,
            "routine_type": r.routine_type,
            "tags": tags,
            "confidence": r.confidence,
            "reuse_count": r.reuse_count,
            "score": round(service.score_routine(r), 3),
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "source_session_id": r.source_session_id,
        })

    return JSONResponse(content={"routines": items, "total": len(items)})


@router.get("/routines/{routine_id}")
async def get_routine(
    routine_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """查看套路详情。"""
    service = LearnService(db, _settings)
    routine = await service.get_routine(routine_id)
    if not routine:
        raise HTTPException(status_code=404, detail="routine not found")

    tags = []
    if routine.tags:
        import json
        try:
            tags = json.loads(routine.tags)
        except Exception:
            pass

    return JSONResponse(content={
        "id": routine.id,
        "status": routine.status,
        "title": routine.title,
        "summary": routine.summary,
        "routine_type": routine.routine_type,
        "content": routine.content,
        "tags": tags,
        "confidence": routine.confidence,
        "reuse_count": routine.reuse_count,
        "score": round(service.score_routine(routine), 3),
        "question_fingerprint": routine.question_fingerprint,
        "source_session_id": routine.source_session_id,
        "source_response_id": routine.source_response_id,
        "last_hit_at": routine.last_hit_at,
        "created_at": routine.created_at,
        "updated_at": routine.updated_at,
    })


@router.patch("/routines/{routine_id}")
async def update_routine(
    routine_id: str,
    body: RoutineUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """更新套路状态（激活/弃用/标记替代）。"""
    service = LearnService(db, _settings)
    routine = await service.update_routine_status(routine_id, body.status)
    if not routine:
        raise HTTPException(status_code=404, detail="routine not found")

    return JSONResponse(content={
        "id": routine.id,
        "status": routine.status,
        "updated_at": routine.updated_at,
    })


@router.post("/routines/{routine_id}/trigger")
async def trigger_routine(
    routine_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """手动触发重评估 — 将 candidate 提升为 active。"""
    service = LearnService(db, _settings)
    routine = await service.get_routine(routine_id)
    if not routine:
        raise HTTPException(status_code=404, detail="routine not found")

    if routine.status == "candidate":
        routine = await service.update_routine_status(routine_id, "active")
        return JSONResponse(content={
            "id": routine.id,
            "status": routine.status,
            "message": "已激活",
        })

    return JSONResponse(content={
        "id": routine.id,
        "status": routine.status,
        "message": f"当前状态 {routine.status}，无需变更",
    })


@router.delete("/routines/{routine_id}")
async def delete_routine(
    routine_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """删除套路。"""
    service = LearnService(db, _settings)
    deleted = await service.delete_routine(routine_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="routine not found")

    return JSONResponse(content={"result": "success", "id": routine_id})


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """获取学习统计。"""
    service = LearnService(db, _settings)
    stats = await service.get_stats()
    return JSONResponse(content=stats)
