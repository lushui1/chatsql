"""Responses API routes — POST /v1/responses, GET /v1/responses/{id}, stream resume."""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.infrastructure import get_db
from app.infrastructure.repositories import conversation_store as store
from app.application.responses.streaming import (
    SSEDone,
    build_sse_event,
    create_stream_context,
    stream_response,
)
from app.application.services.responses_service import ResponsesService
from app.presentation.http.security.auth_utils import (
    get_session_id,
    get_session_mode,
    verify_api_key,
)
from app.schemas import (
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    ResponseCreateRequest,
)

router = APIRouter(prefix="/v1")
_settings = get_settings()


@router.post("/responses")
async def create_response(
    request: Request,
    body: ResponseCreateRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
    x_session_id: str | None = Header(None),
    x_smartbot_mode: str | None = Header(None),
):
    """Create a response — OpenAI Responses API compatible."""
    # Parse session headers
    session_id = get_session_id(x_session_id)
    mode = get_session_mode(x_smartbot_mode)

    service = ResponsesService(db, _settings)

    # Resolve or create session
    if session_id:
        session = await store.get_session(db, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        # Validate mode
        if mode is None:
            raise HTTPException(status_code=400, detail="mode must be fast or think")
        if session.mode and session.mode != mode:
            raise HTTPException(status_code=400, detail="session mode mismatch")
    else:
        if mode is None:
            raise HTTPException(status_code=400, detail="mode must be fast or think")
        session = await store.create_session(db, mode=mode)
        session_id = session.id

    # Normalize input to list format
    input_items = service.normalize_input(body.input)

    # Create response record
    model = body.model or (mode == "think" and _settings.llm_think_model or _settings.llm_model)
    resp = await store.create_response(db, session_id=session_id, input_items=input_items, model=model)

    # Mark session as streaming
    await store.update_session_stream_state(
        db, session_id, streaming=True, active_response_id=resp.id, active_stream_sequence=0,
        active_request_input=input_items,
    )

    if body.stream:
        return StreamingResponse(
            _stream_generator(db, service, resp.id, session_id, body, input_items, model),
            media_type="text/event-stream",
            headers={
                "X-Session-Id": session_id,
                "X-Session-Mode": mode,
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Response-Id": resp.id,
            },
        )
    else:
        # Non-streaming: run to completion
        result = await service.run_completion(
            response_id=resp.id,
            session_id=session_id,
            input_items=input_items,
            model=model,
            instructions=body.instructions,
            tools=body.tools,
            temperature=body.temperature,
            max_tokens=body.max_output_tokens,
        )
        return JSONResponse(
            content=result.model_dump(),
            headers={"X-Session-Id": session_id, "X-Session-Mode": mode},
        )


async def _stream_generator(
    db: AsyncSession,
    service: ResponsesService,
    response_id: str,
    session_id: str,
    body: ResponseCreateRequest,
    input_items: list[dict],
    model: str,
) -> AsyncGenerator[str, None]:
    """Generate SSE events for a streaming response."""
    ctx = create_stream_context(response_id)

    try:
        async for event in stream_response(service, ctx, input_items, model, body):
            # Update sequence in DB
            seq = ctx.next_sequence()
            event_data = {**event, "sequence_number": seq}
            yield build_sse_event(event_data)

        # Done
        yield SSEDone
    except Exception as e:
        # Emit failure event
        error_event = {
            "type": "response.failed",
            "error": {"code": "internal_error", "message": str(e)},
            "sequence_number": ctx.next_sequence(),
        }
        yield build_sse_event(error_event)
        yield SSEDone
    finally:
        # Update DB state
        await store.update_session_stream_state(
            db, session_id, streaming=False, active_response_id=None,
            active_stream_sequence=None, active_request_input=None,
        )


@router.get("/responses/{response_id}")
async def get_response(
    response_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
    stream: bool | None = Query(None),
    starting_after: int | None = Query(None),
):
    """Get a response by ID, or resume SSE stream if stream=true."""
    resp = await store.get_response(db, response_id)
    if resp is None:
        raise HTTPException(status_code=404, detail="response not found")

    if stream:
        # Stream resume — for now return current state (active stream buffer is process-local)
        # In production this would replay buffered events + continue live
        raise HTTPException(status_code=404, detail="active stream not found")

    import json as _json
    output = _json.loads(resp.output_json) if resp.output_json else []
    return JSONResponse(content={
        "id": resp.id,
        "object": "response",
        "created_at": resp.created_at,
        "status": resp.status,
        "model": resp.model,
        "output": output,
        "usage": {
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
            "total_tokens": resp.input_tokens + resp.output_tokens,
        },
        "error": _json.loads(resp.error_json) if resp.error_json else None,
    })


@router.post("/responses/{response_id}/feedbacks")
async def toggle_feedback(
    response_id: str,
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Toggle like feedback on a response."""
    resp = await store.get_response(db, response_id)
    if resp is None:
        raise HTTPException(status_code=404, detail="response not found")
    result = await store.toggle_feedback(db, response_id, content=body.content)
    return FeedbackResponse(result="success", feedback=result)
