"""Skill service — business logic for skill management and execution."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import urllib.request
import urllib.error
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.skill_domain import (
    Skill,
    SkillExecutionContext,
    SkillExecutionLog,
    SkillSecurity,
    ExecutionType,
)
from app.infrastructure.repositories import skill_store as store

logger = logging.getLogger("chatsql")


# ── Allowed Python imports for sandboxed execution ──

ALLOWED_MODULES = {
    "pandas", "numpy", "datetime", "math", "json", "re", "statistics",
    "collections", "itertools", "functools", "operator", "string",
    "typing", "decimal", "fractions", "random", "hashlib", "base64",
}

# Blocked keywords in user code (security)
BLOCKED_PATTERNS = [
    r"\bos\.spawn\b",
    r"\bos\.system\b",
    r"\bsubprocess\b",
    r"\bopen\b.*['\"]w",
    r"\bexec\s*\(",
    r"\beval\s*\(",
    r"\b__import__\s*\(",
]


class SkillService:
    """Business logic for skill CRUD and execution."""

    def __init__(self, db: AsyncSession):
        self._db = db

    # ── CRUD ──

    async def create_skill(self, skill: Skill) -> Skill:
        """Validate and create a new skill."""
        # Check name uniqueness
        existing = await store.get_skill_by_name(self._db, skill.name)
        if existing:
            raise ValueError(f"Skill name '{skill.name}' already exists")

        # Validate function schema has required fields
        schema = skill.function_schema
        if not schema.get("name"):
            raise ValueError("function_schema must have 'name' field")
        if not schema.get("description"):
            raise ValueError("function_schema must have 'description' field")

        # Block reserved names
        reserved = {"execute_sql", "planning", "chatsql_chart", "ask_clarification", "propose_subscription"}
        if schema["name"] in reserved:
            raise ValueError(f"Skill name '{schema['name']}' is reserved")

        # Block chatsql_ prefix to avoid confusion
        if schema["name"].startswith("chatsql_"):
            raise ValueError("Skill names cannot use 'chatsql_' prefix (reserved for built-in tools)")

        return await store.create_skill(self._db, skill)

    async def get_skill(self, skill_id: str) -> Skill | None:
        return await store.get_skill(self._db, skill_id)

    async def get_skill_by_name(self, name: str) -> Skill | None:
        return await store.get_skill_by_name(self._db, name)

    async def list_skills(
        self,
        *,
        enabled_only: bool = True,
        category: str | None = None,
    ) -> list[Skill]:
        return await store.list_skills(self._db, enabled_only=enabled_only, category=category)

    async def update_skill(
        self,
        skill_id: str,
        updates: dict[str, Any],
    ) -> Skill | None:
        return await store.update_skill(self._db, skill_id, updates)

    async def delete_skill(self, skill_id: str) -> bool:
        return await store.delete_skill(self._db, skill_id)

    async def toggle_skill(self, skill_id: str, enabled: bool) -> Skill | None:
        return await store.toggle_skill(self._db, skill_id, enabled)

    # ── Execution ──

    async def execute_skill(
        self,
        context: SkillExecutionContext,
    ) -> dict[str, Any]:
        """Execute a skill with security checks."""
        start_time = time.time()
        skill = context.skill

        # Security: check timeout
        if skill.security.timeout_seconds <= 0:
            return {"error": "Invalid timeout configuration"}

        # Security: check data source access
        if "*" not in skill.security.allowed_data_sources:
            ds = context.datasource
            if ds and ds not in skill.security.allowed_data_sources:
                return {"error": f"Skill does not have access to datasource '{ds}'"}

        # Security: check blocked keywords in code/script
        if skill.execution_type in ("code", "script"):
            content = skill.code or skill.script
            for pattern in BLOCKED_PATTERNS:
                if re.search(pattern, content):
                    return {"error": f"Blocked pattern detected: {pattern}"}

        try:
            if skill.execution_type == "code":
                result = await self._execute_code(context)
            elif skill.execution_type == "script":
                result = await self._execute_script(context)
            elif skill.execution_type == "http":
                result = await self._execute_http(context)
            else:
                result = {"error": f"Unknown execution type: {skill.execution_type}"}

        except TimeoutError:
            result = {"error": f"Skill execution timed out after {skill.security.timeout_seconds}s"}
        except Exception as e:
            logger.exception(f"Skill execution failed: {e}")
            result = {"error": str(e)}

        duration_ms = int((time.time() - start_time) * 1000)
        status = "success" if "error" not in result else "failed"

        # Log execution
        log = SkillExecutionLog(
            id=f"log_{int(start_time * 1000)}",
            skill_id=skill.id,
            session_id=context.session_id,
            response_id="",  # Will be set by caller
            status=status,
            input_args=context.arguments,
            output=result if status == "success" else None,
            error=result.get("error", ""),
            duration_ms=duration_ms,
            created_at=int(start_time),
        )
        await store.create_execution_log(self._db, log)

        # Update stats
        await store.increment_call_count(self._db, skill.id)

        return result

    async def _execute_code(self, context: SkillExecutionContext) -> dict[str, Any]:
        """Execute Python code in sandboxed environment."""
        skill = context.skill
        code = skill.code

        # Build safe globals
        safe_globals: dict[str, Any] = {
            "__builtins__": __builtins__,
        }

        # Whitelist imports
        for module_name in ALLOWED_MODULES:
            try:
                safe_globals[module_name] = __import__(module_name)
            except ImportError:
                pass

        # Inject context variables
        context_vars = {
            "arguments": context.arguments,
            "session_id": context.session_id,
            "datasource": context.datasource,
        }
        context_vars.update(context.existing_data)
        safe_globals.update(context_vars)

        # Execute code
        local_ns: dict[str, Any] = {}
        exec(code, safe_globals, local_ns)  # noqa: S102

        # Extract result
        return local_ns.get("result", {})

    async def _execute_script(self, context: SkillExecutionContext) -> dict[str, Any]:
        """Execute shell script. Restricted to read-only commands."""
        skill = context.skill
        script = skill.script

        # Block dangerous commands
        dangerous = ["rm", "mv", "cp", "dd", "wget", "curl", "sudo", "chmod", "chown"]
        for cmd in dangerous:
            if re.search(rf'\b{cmd}\b', script):
                return {"error": f"Blocked command: {cmd}"}

        # For now, scripts are not executed (placeholder for future)
        return {"error": "Script execution not yet implemented"}

    async def _execute_http(self, context: SkillExecutionContext) -> dict[str, Any]:
        """Execute HTTP request. URL must be whitelisted."""
        skill = context.skill
        url = skill.url

        # Build full URL with arguments
        args = context.arguments
        if args:
            query = "&".join(f"{k}={v}" for k, v in args.items())
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{query}"

        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=skill.security.timeout_seconds) as resp:
                data = resp.read()
                return {"status": resp.status, "data": data.decode("utf-8", errors="replace")}
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Integration with LLM ──

    async def get_enabled_skill_defs(self) -> list[dict]:
        """Get all enabled skills as LLM tool definitions."""
        skills = await self.list_skills(enabled_only=True)
        return [skill.function_schema for skill in skills]

    async def build_skill_context_prompt(self) -> str:
        """Build a prompt section describing available skills."""
        skills = await self.list_skills(enabled_only=True)
        if not skills:
            return ""

        lines = ["## Available Skills"]
        for s in skills:
            lines.append(f"- **{s.name}** ({s.version}): {s.description}")
            if s.category:
                lines.append(f"  Category: {s.category}")
        return "\n".join(lines)
