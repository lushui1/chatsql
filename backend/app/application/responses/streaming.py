"""SSE streaming — event builder, stream context, response streamer."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import field
from typing import AsyncGenerator

from dataclasses import dataclass


SSEDone = "data: [DONE]\n\n"


@dataclass
class StreamContext:
    """Tracks sequence numbers for an active SSE stream."""

    response_id: str
    _seq: int = 0

    def next_sequence(self) -> int:
        self._seq += 1
        return self._seq

    @property
    def current_sequence(self) -> int:
        return self._seq


def create_stream_context(response_id: str) -> StreamContext:
    return StreamContext(response_id=response_id)


def build_sse_event(data: dict) -> str:
    """Build a single SSE event string."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_response(
    service,
    ctx: StreamContext,
    input_items: list[dict],
    model: str,
    body,
) -> AsyncGenerator[dict, None]:
    """Stream a response: emit created → in_progress → content → completed.

    This is the core streaming pipeline that:
    1. Emits response.created
    2. Calls the LLM (via service)
    3. Emits text deltas as they arrive
    4. Emits function_call events for tool calls
    5. Emits response.completed with full output
    """
    now = int(time.time())

    # 1. Created
    yield {
        "type": "response.created",
        "response": {
            "id": ctx.response_id,
            "object": "response",
            "created_at": now,
            "status": "in_progress",
            "model": model,
            "output": [],
        },
    }

    # 2. In progress
    yield {
        "type": "response.in_progress",
        "response": {
            "id": ctx.response_id,
            "object": "response",
            "status": "in_progress",
            "model": model,
            "output": [],
        },
    }

    # 3. Call LLM and stream output
    try:
        output_items: list[dict] = []
        full_text = ""

        async for chunk in service.call_llm_stream(input_items, model, body.instructions, body.tools):
            if chunk["type"] == "text_delta":
                full_text += chunk["text"]
                yield {
                    "type": "response.output_text.delta",
                    "delta": chunk["text"],
                }
            elif chunk["type"] == "text_done":
                msg_item = {
                    "type": "message",
                    "id": f"msg_{ctx.response_id}",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": full_text}],
                    "status": "completed",
                }
                output_items.append(msg_item)
                yield {
                    "type": "response.output_item.done",
                    "item": msg_item,
                }
            elif chunk["type"] == "function_call":
                fc_item = {
                    "type": "function_call",
                    "id": f"fc_{ctx.response_id}_{len(output_items)}",
                    "call_id": chunk["call_id"],
                    "name": chunk["name"],
                    "arguments": chunk["arguments"],
                    "status": "completed",
                }
                output_items.append(fc_item)
                yield {
                    "type": "response.output_item.added",
                    "item": fc_item,
                }
                yield {
                    "type": "response.function_call_arguments.done",
                    "call_id": chunk["call_id"],
                    "arguments": chunk["arguments"],
                }

        # 4. Completed
        yield {
            "type": "response.completed",
            "response": {
                "id": ctx.response_id,
                "object": "response",
                "created_at": now,
                "status": "completed",
                "model": model,
                "output": output_items,
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            },
        }

        # Persist the completed response
        await service.complete_response(ctx.response_id, output_items)

    except Exception as e:
        yield {
            "type": "response.failed",
            "error": {"code": "internal_error", "message": str(e)},
        }
        raise
