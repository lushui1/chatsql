"""Pydantic schemas — request/response models for Responses API."""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field


# ── Request Models ──

class InputTextContent(BaseModel):
    type: Literal["input_text"] = "input_text"
    text: str


class MessageInputItem(BaseModel):
    type: Literal["message"] = "message"
    role: Literal["user", "assistant", "system", "developer"] = "user"
    content: list[InputTextContent]


class FunctionCallOutputItem(BaseModel):
    type: Literal["function_call_output"] = "function_call_output"
    call_id: str
    output: str


InputItem = Union[MessageInputItem, FunctionCallOutputItem, dict]


class ResponseCreateRequest(BaseModel):
    """POST /v1/responses request body — OpenAI Responses API compatible."""

    model: str | None = None
    input: Union[str, list[InputItem]] = Field(...)
    previous_response_id: str | None = None
    tools: list[dict] | None = None
    tool_choice: Any = "auto"
    stream: bool = False
    instructions: str | None = None
    metadata: dict | None = None
    temperature: float | None = None
    top_p: float | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    max_output_tokens: int | None = None
    max_tool_calls: int | None = None
    parallel_tool_calls: bool | None = None
    store: bool = True


# ── Response Models ──

class OutputTextContent(BaseModel):
    type: Literal["output_text"] = "output_text"
    text: str


class MessageOutputItem(BaseModel):
    type: Literal["message"] = "message"
    id: str
    role: Literal["assistant"] = "assistant"
    content: list[OutputTextContent]
    status: str = "completed"


class FunctionCallItem(BaseModel):
    type: Literal["function_call"] = "function_call"
    id: str
    call_id: str
    name: str
    arguments: str
    status: str = "completed"


OutputItem = Union[MessageOutputItem, FunctionCallItem, dict]


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ResponseResource(BaseModel):
    """Non-streaming response — GET or non-stream POST."""

    id: str
    object: Literal["response"] = "response"
    created_at: int
    status: Literal["completed", "failed", "in_progress"] = "completed"
    model: str = ""
    output: list[OutputItem] = []
    usage: Usage = Field(default_factory=Usage)
    error: dict | None = None


# ── Session Models ──

class SessionItem(BaseModel):
    id: str
    title: str
    created_at: int
    updated_at: int
    first_response_id: str | None = None
    last_response_id: str | None = None
    response_count: int | None = None
    last_response_model: str | None = None
    last_response_status: str | None = None
    last_response_at: int | None = None
    mode: str | None = None  # "fast" | "think"
    streaming: bool = False
    active_response_id: str | None = None
    active_stream_sequence: int | None = None


class SessionUpdateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=64)


# ── Response Turns ──

class ResponseTurn(BaseModel):
    response_id: str
    request_input: list[dict] = []
    output: list[dict] = []
    created_at: int
    feedback: str | None = None  # "like" | None


class ResponseTurnsPage(BaseModel):
    turns: list[ResponseTurn]
    next_cursor: str | None = None
    prev_cursor: str | None = None


# ── Feedback ──

class FeedbackRequest(BaseModel):
    content: str | None = None


class FeedbackResponse(BaseModel):
    result: str = "success"
    feedback: str | None = None  # "like" | None


# ── Suggested ──

class SuggestedResponse(BaseModel):
    result: str = "success"
    data: list[str] = []


# ── Error ──

class ErrorBody(BaseModel):
    code: Literal["invalid_request_error", "internal_error"] = "invalid_request_error"
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
