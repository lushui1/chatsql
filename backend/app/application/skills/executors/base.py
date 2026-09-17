"""Skill executors — execute different types of skills."""

from __future__ import annotations

from typing import Any

from app.domain.skill_domain import SkillExecutionContext


class BaseExecutor:
    """Base class for skill executors."""

    def __init__(self, context: SkillExecutionContext):
        self.context = context
        self.skill = context.skill

    async def execute(self) -> dict[str, Any]:
        raise NotImplementedError


class CodeExecutor(BaseExecutor):
    """Execute Python code in sandboxed environment."""

    ALLOWED_MODULES = {
        "pandas", "numpy", "datetime", "math", "json", "re", "statistics",
        "collections", "itertools", "functools", "operator", "string",
        "typing", "decimal", "fractions", "random", "hashlib", "base64",
    }

    BLOCKED_PATTERNS = [
        r"\bos\.spawn\b",
        r"\bos\.system\b",
        r"\bsubprocess\b",
        r"\bopen\b.*['\"]w",
        r"\bexec\s*\(",
        r"\beval\s*\(",
        r"\b__import__\s*\(",
    ]

    async def execute(self) -> dict[str, Any]:
        code = self.skill.code
        if not code:
            return {"error": "No code defined"}

        # Security checks
        import re
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, code):
                return {"error": f"Blocked pattern detected: {pattern}"}

        # Build safe globals
        safe_globals: dict[str, Any] = {"__builtins__": __builtins__}

        # Inject allowed modules
        for module_name in self.ALLOWED_MODULES:
            try:
                safe_globals[module_name] = __import__(module_name)
            except ImportError:
                pass

        # Inject context variables
        context_vars = {
            "arguments": self.context.arguments,
            "session_id": self.context.session_id,
            "datasource": self.context.datasource,
        }
        context_vars.update(self.context.existing_data)
        safe_globals.update(context_vars)

        # Execute
        local_ns: dict[str, Any] = {}
        exec(code, safe_globals, local_ns)  # noqa: S102

        return local_ns.get("result", {})


class ScriptExecutor(BaseExecutor):
    """Execute shell scripts (restricted)."""

    DANGEROUS_COMMANDS = ["rm", "mv", "cp", "dd", "wget", "curl", "sudo", "chmod", "chown"]

    async def execute(self) -> dict[str, Any]:
        script = self.skill.script
        if not script:
            return {"error": "No script defined"}

        # Check for dangerous commands
        import re
        for cmd in self.DANGEROUS_COMMANDS:
            if re.search(rf'\b{cmd}\b', script):
                return {"error": f"Blocked command: {cmd}"}

        return {"error": "Script execution not yet implemented"}


class HttpExecutor(BaseExecutor):
    """Execute HTTP requests."""

    async def execute(self) -> dict[str, Any]:
        import urllib.request
        import urllib.error

        url = self.skill.url
        args = self.context.arguments

        # Build query string
        if args:
            query = "&".join(f"{k}={v}" for k, v in args.items())
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{query}"

        try:
            req = urllib.request.Request(url, method="GET")
            timeout = self.skill.security.timeout_seconds
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                return {"status": resp.status, "data": data.decode("utf-8", errors="replace")}
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}


def get_executor(execution_type: str, context: SkillExecutionContext) -> BaseExecutor:
    """Factory function to get the right executor."""
    executors = {
        "code": CodeExecutor,
        "script": ScriptExecutor,
        "http": HttpExecutor,
    }
    executor_cls = executors.get(execution_type)
    if not executor_cls:
        raise ValueError(f"Unknown execution type: {execution_type}")
    return executor_cls(context)
