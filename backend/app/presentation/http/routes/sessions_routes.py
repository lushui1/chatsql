"""Session management routes — list, delete, rename, history, suggested."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure import get_db
from app.infrastructure.repositories import conversation_store as store
from app.presentation.http.security.auth_utils import verify_api_key
from app.schemas import SessionUpdateRequest

router = APIRouter(prefix="/v1")


@router.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """List all sessions."""
    sessions = await store.list_sessions(db)
    return JSONResponse(content=[
        {
            "id": s.id,
            "title": s.title,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
            "first_response_id": s.first_response_id,
            "last_response_id": s.last_response_id,
            "response_count": s.response_count,
            "last_response_model": s.last_response_model,
            "last_response_status": s.last_response_status,
            "last_response_at": s.last_response_at,
            "mode": s.mode,
            "streaming": s.streaming,
            "active_response_id": s.active_response_id,
            "active_stream_sequence": s.active_stream_sequence,
        }
        for s in sessions
    ])


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Delete a session and all its responses."""
    deleted = await store.delete_session(db, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    return JSONResponse(status_code=204, content=None)


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str,
    body: SessionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Update session title."""
    session = await store.update_session_title(db, session_id, body.title)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return JSONResponse(content={
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "mode": session.mode,
    })


@router.get("/sessions/{session_id}/response-turns")
async def get_response_turns(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
    cursor: str | None = Query(None),
    direction: str = Query("next"),
    limit: int = Query(50, ge=1, le=200),
):
    """Get paginated response turns for a session."""
    session = await store.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    # cursor is a timestamp (int as string)
    cursor_int = int(cursor) if cursor else None
    result = await store.get_response_turns(
        db, session_id, cursor=cursor_int, direction=direction, limit=limit
    )
    return JSONResponse(content=result)


@router.get("/suggested")
async def get_suggested(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Return suggested questions (static for now, LLM-powered in future)."""
    return JSONResponse(content={
        "result": "success",
        "data": [
            "最近7天各城市单量趋势",
            "装载率最低的10条线路",
            "本月GMV同比上月",
            "各分拣中心货量占比",
            "时效异常的网点有哪些",
        ],
    })
