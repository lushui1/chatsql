"""Session repository — CRUD for sessions and responses."""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

from sqlalchemy import select, update, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.models import Session as SessionModel, Response as ResponseModel, Feedback


def _new_session_id() -> str:
    return f"sess_{secrets.token_hex(16)}"


def _new_response_id() -> str:
    return f"resp_{secrets.token_hex(16)}"


# ── Sessions ──

async def create_session(db: AsyncSession, *, mode: str | None = None, title: str = "新对话") -> SessionModel:
    session = SessionModel(
        id=_new_session_id(),
        title=title,
        mode=mode,
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_session(db: AsyncSession, session_id: str) -> SessionModel | None:
    result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
    return result.scalar_one_or_none()


async def list_sessions(db: AsyncSession) -> list[SessionModel]:
    result = await db.execute(select(SessionModel).order_by(desc(SessionModel.updated_at)))
    return list(result.scalars().all())


async def delete_session(db: AsyncSession, session_id: str) -> bool:
    # Delete responses + feedback first
    await db.execute(
        ResponseModel.__table__.delete().where(ResponseModel.session_id == session_id)
    )
    await db.execute(
        Feedback.__table__.delete().where(Feedback.session_id == session_id)
    )
    result = await db.execute(
        SessionModel.__table__.delete().where(SessionModel.id == session_id)
    )
    await db.commit()
    return result.rowcount > 0


async def update_session_title(db: AsyncSession, session_id: str, title: str) -> SessionModel | None:
    await db.execute(
        update(SessionModel).where(SessionModel.id == session_id).values(title=title, updated_at=int(time.time()))
    )
    await db.commit()
    return await get_session(db, session_id)


async def update_session_stream_state(
    db: AsyncSession,
    session_id: str,
    *,
    streaming: bool,
    active_response_id: str | None = None,
    active_stream_sequence: int | None = None,
    active_request_input: list | None = None,
) -> None:
    values: dict[str, Any] = {"streaming": streaming, "updated_at": int(time.time())}
    if active_response_id is not None:
        values["active_response_id"] = active_response_id
    if active_stream_sequence is not None:
        values["active_stream_sequence"] = active_stream_sequence
    if active_request_input is not None:
        values["active_request_input"] = json.dumps(active_request_input, ensure_ascii=False)
    await db.execute(update(SessionModel).where(SessionModel.id == session_id).values(**values))
    await db.commit()


# ── Responses ──

async def create_response(
    db: AsyncSession,
    *,
    session_id: str,
    input_items: list[dict],
    model: str = "",
) -> ResponseModel:
    resp = ResponseModel(
        id=_new_response_id(),
        session_id=session_id,
        created_at=int(time.time()),
        model=model,
        status="in_progress",
        input_json=json.dumps(input_items, ensure_ascii=False),
    )
    db.add(resp)
    await db.commit()
    await db.refresh(resp)
    return resp


async def complete_response(
    db: AsyncSession,
    response_id: str,
    *,
    output_items: list[dict],
    status: str = "completed",
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    error: dict | None = None,
) -> ResponseModel | None:
    result = await db.execute(select(ResponseModel).where(ResponseModel.id == response_id))
    resp = result.scalar_one_or_none()
    if resp is None:
        return None
    resp.output_json = json.dumps(output_items, ensure_ascii=False)
    resp.status = status
    resp.completed_at = int(time.time())
    resp.model = model or resp.model
    resp.input_tokens = input_tokens
    resp.output_tokens = output_tokens
    resp.error_json = json.dumps(error, ensure_ascii=False) if error else None

    # Update session counters
    sess_result = await db.execute(select(SessionModel).where(SessionModel.id == resp.session_id))
    sess = sess_result.scalar_one_or_none()
    if sess:
        sess.last_response_id = response_id
        sess.last_response_model = resp.model
        sess.last_response_status = status
        sess.last_response_at = resp.completed_at
        if not sess.first_response_id:
            sess.first_response_id = response_id
        sess.response_count = (sess.response_count or 0) + 1
        sess.streaming = False
        sess.updated_at = int(time.time())

    await db.commit()
    return resp


async def get_response(db: AsyncSession, response_id: str) -> ResponseModel | None:
    result = await db.execute(select(ResponseModel).where(ResponseModel.id == response_id))
    return result.scalar_one_or_none()


async def get_response_turns(
    db: AsyncSession,
    session_id: str,
    *,
    cursor: int | None = None,
    direction: str = "next",
    limit: int = 50,
) -> dict:
    """Paginated response turns for a session."""
    query = select(ResponseModel).where(ResponseModel.session_id == session_id)

    if cursor is not None:
        if direction == "next":
            query = query.where(ResponseModel.created_at < cursor)
        else:
            query = query.where(ResponseModel.created_at > cursor)

    query = query.order_by(desc(ResponseModel.created_at)).limit(limit)
    result = await db.execute(query)
    rows = list(result.scalars().all())

    # Fetch feedback for these responses
    resp_ids = [r.id for r in rows]
    fb_result = await db.execute(select(Feedback).where(Feedback.response_id.in_(resp_ids)))
    feedbacks = {f.response_id: f for f in fb_result.scalars().all()}

    turns = []
    for r in reversed(rows):  # chronological order
        output = json.loads(r.output_json) if r.output_json else []
        input_items = json.loads(r.input_json) if r.input_json else []
        fb = feedbacks.get(r.id)
        turns.append({
            "response_id": r.id,
            "request_input": input_items,
            "output": output,
            "created_at": r.created_at,
            "feedback": fb.kind if fb else None,
        })

    next_cursor = rows[-1].created_at if len(rows) == limit and rows else None
    prev_cursor = rows[0].created_at if rows else None

    return {
        "turns": turns,
        "next_cursor": next_cursor,
        "prev_cursor": prev_cursor if direction == "next" else None,
    }


# ── Feedback ──

async def toggle_feedback(db: AsyncSession, response_id: str, *, content: str | None = None) -> str | None:
    # Find existing
    result = await db.execute(select(Feedback).where(Feedback.response_id == response_id))
    existing = result.scalar_one_or_none()

    if existing:
        await db.delete(existing)
        await db.commit()
        return None
    else:
        # Get session_id from response
        resp = await get_response(db, response_id)
        session_id = resp.session_id if resp else ""
        fb = Feedback(response_id=response_id, session_id=session_id, kind="like", content=content)
        db.add(fb)
        await db.commit()
        return "like"
