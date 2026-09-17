"""Skill domain models — user-defined tools for LLM."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


# ── Execution Types ──

ExecutionType = Literal["code", "script", "http"]


# ── Security Policy ──


class SkillSecurity(BaseModel):
    """Security policy for skill execution."""
    timeout_seconds: int = 30
    max_rows: int = 10_000
    allowed_data_sources: list[str] = Field(default_factory=lambda: ["*"])
    requires_approval: bool = False
    sandbox_mode: bool = True
    blocked_keywords: list[str] = Field(default_factory=list)


# ── Skill Definition ──


class Skill(BaseModel):
    """User-defined skill that extends the LLM's capabilities."""
    id: str
    name: str                              # Unique identifier, e.g. "sales_dashboard"
    version: str = "1.0"                   # Semantic version
    description: str                       # What this skill does (for LLM understanding)
    enabled: bool = True                   # Whether this skill is active
    
    # Function schema (OpenAI tool format)
    function_schema: dict                  # Complete tool definition
    
    # Execution type
    execution_type: ExecutionType          # code | script | http
    
    # Content based on type
    code: str = ""                         # Python code (for code type)
    script: str = ""                       # Shell script (for script type)
    url: str = ""                          # Target URL (for http type)
    
    # Security
    security: SkillSecurity = Field(default_factory=SkillSecurity)
    
    # Metadata
    created_by: str = ""                   # User who created this skill
    created_at: int = 0
    updated_at: int = 0
    tags: list[str] = Field(default_factory=list)
    category: str = ""                     # e.g., "analytics", "reporting", "automation"
    
    # Usage stats
    call_count: int = 0
    last_used_at: int = 0


class SkillExecutionLog(BaseModel):
    """Execution log for a skill invocation."""
    id: str
    skill_id: str
    session_id: str
    response_id: str
    status: str                            # success | failed | timeout | denied
    input_args: dict = Field(default_factory=dict)
    output: dict | None = None
    error: str = ""
    duration_ms: int = 0
    created_at: int = 0


# ── Skill Execution Context ──


class SkillExecutionContext(BaseModel):
    """Context passed to skill executor."""
    skill: Skill
    arguments: dict
    session_id: str
    datasource: str | None = None
    existing_data: dict = Field(default_factory=dict)  # Pre-loaded data from previous tool calls
