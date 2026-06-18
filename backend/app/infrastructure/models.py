"""SQLAlchemy ORM models — sessions, responses, feedback."""

from __future__ import annotations

import time

from sqlalchemy import Column, Integer, String, Text, Boolean, Index
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def _now() -> int:
    return int(time.time())


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(64), primary_key=True)  # sess_<32hex>
    title = Column(String(128), default="新对话")
    mode = Column(String(16), nullable=True)  # fast | think
    created_at = Column(Integer, default=_now)
    updated_at = Column(Integer, default=_now, onupdate=_now)
    first_response_id = Column(String(64), nullable=True)
    last_response_id = Column(String(64), nullable=True)
    response_count = Column(Integer, default=0)
    last_response_model = Column(String(64), nullable=True)
    last_response_status = Column(String(32), nullable=True)
    last_response_at = Column(Integer, nullable=True)
    # Active stream state (in-DB snapshot, best-effort)
    streaming = Column(Boolean, default=False)
    active_response_id = Column(String(64), nullable=True)
    active_stream_sequence = Column(Integer, nullable=True)
    active_request_input = Column(Text, nullable=True)  # JSON


class Response(Base):
    """One response = one turn (user input + assistant output)."""

    __tablename__ = "responses"

    id = Column(String(64), primary_key=True)  # resp_<32hex>
    session_id = Column(String(64), nullable=False, index=True)
    created_at = Column(Integer, default=_now)
    completed_at = Column(Integer, nullable=True)
    model = Column(String(64), default="")
    status = Column(String(32), default="in_progress")  # in_progress | completed | failed
    input_json = Column(Text, nullable=True)  # JSON: original input items
    output_json = Column(Text, nullable=True)  # JSON: output items
    error_json = Column(Text, nullable=True)
    # Usage
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)


class Feedback(Base):
    """User feedback (like) on a response."""

    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    response_id = Column(String(64), nullable=False, index=True)
    session_id = Column(String(64), nullable=False)
    kind = Column(String(16), default="like")  # like | dislike (future)
    content = Column(Text, nullable=True)
    created_at = Column(Integer, default=_now)


# Indices
Index("ix_responses_session_created", Response.session_id, Response.created_at)
Index("ix_feedbacks_response", Feedback.response_id)
