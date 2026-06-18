"""LLM Provider abstraction layer — plugin architecture for multiple LLM backends.

Usage:
    from app.application.llm import get_provider
    provider = get_provider(settings)
    async for chunk in provider.stream_chat(messages, tools, model, temperature, max_tokens):
        ...
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator

from app.config import Settings

# ──────────────────────────────────────────────────────────────
# Provider defaults: base_url + suggested models per provider
# ──────────────────────────────────────────────────────────────

PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "models": ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"],
    },
    "google": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    },
    "dashscope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen-long"],
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-plus", "glm-4-flash", "glm-4-air"],
    },
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-8k"],
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "models": ["llama3.1", "qwen2.5", "deepseek-r1"],
    },
    "custom": {
        "base_url": "",
        "models": [],
    },
}


def get_provider_base_url(provider: str, override: str = "") -> str:
    """Return the effective base_url for a provider."""
    if override:
        return override
    return PROVIDER_DEFAULTS.get(provider, {}).get("base_url", "")


# ──────────────────────────────────────────────────────────────
# Abstract Provider
# ──────────────────────────────────────────────────────────────


class LLMProvider(ABC):
    """Abstract LLM provider — streams chat completions in a unified chunk format."""

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream chat completions.

        Yields chunks in unified format:
            {"type": "text_delta", "text": "..."}
            {"type": "function_call", "call_id": "...", "name": "...", "arguments": "..."}
            {"type": "text_done", "text": "..."}  — emitted once at the end
        """
        ...
        # Make this an async generator
        yield {}  # pragma: no cover


# ──────────────────────────────────────────────────────────────
# OpenAI-compatible Provider (base for many providers)
# ──────────────────────────────────────────────────────────────


class OpenAIProvider(LLMProvider):
    """Standard OpenAI API provider — also serves as base for OpenAI-compatible APIs.

    Used directly for: openai, dashscope, zhipu, moonshot, deepseek, custom.
    """

    def __init__(self, api_key: str, base_url: str):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=api_key or "dummy", base_url=base_url)

    def _convert_tools(self, tools: list[dict] | None) -> list[dict] | None:
        """Convert internal tool format to OpenAI function-calling format."""
        if not tools:
            return None
        return [
            {"type": "function", "function": {k: v for k, v in t.items() if k != "type"}}
            for t in tools
        ]

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[dict[str, Any], None]:
        openai_tools = self._convert_tools(tools)

        stream = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            tools=openai_tools,
            stream=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        current_tool_call: dict | None = None
        full_text = ""

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # Text content
            if delta.content:
                full_text += delta.content
                yield {"type": "text_delta", "text": delta.content}

            # Tool calls
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    if tc.id:  # New tool call starts
                        if current_tool_call:
                            yield {
                                "type": "function_call",
                                "call_id": current_tool_call["call_id"],
                                "name": current_tool_call["name"],
                                "arguments": current_tool_call["arguments"],
                            }
                        current_tool_call = {
                            "call_id": tc.id,
                            "name": tc.function.name if tc.function else "",
                            "arguments": "",
                        }
                    if tc.function and tc.function.arguments:
                        if current_tool_call:
                            current_tool_call["arguments"] += tc.function.arguments

        # Text done
        if full_text:
            yield {"type": "text_done", "text": full_text}

        # Finish pending tool call
        if current_tool_call:
            yield {
                "type": "function_call",
                "call_id": current_tool_call["call_id"],
                "name": current_tool_call["name"],
                "arguments": current_tool_call["arguments"],
            }


# ──────────────────────────────────────────────────────────────
# Anthropic Provider (Claude series)
# ──────────────────────────────────────────────────────────────


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider — uses the Messages API via SDK."""

    def __init__(self, api_key: str, base_url: str = ""):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            )
        kwargs: dict[str, Any] = {"api_key": api_key or "dummy"}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = anthropic.AsyncAnthropic(**kwargs)

    def _convert_messages(self, messages: list[dict]) -> tuple[str, list[dict]]:
        """Convert OpenAI-style messages to Anthropic format.

        Returns (system_prompt, messages) tuple.
        """
        system_parts: list[str] = []
        anthropic_messages: list[dict] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                if isinstance(content, str):
                    system_parts.append(content)
            elif role == "tool":
                # Tool results → user messages with tool_result content
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": content,
                    }],
                })
            elif role == "assistant":
                # Check if message has tool_calls
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    content_blocks: list[dict] = []
                    if content:
                        content_blocks.append({"type": "text", "text": content})
                    for tc in tool_calls:
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc.get("id", ""),
                            "name": tc.get("function", {}).get("name", ""),
                            "input": json.loads(tc.get("function", {}).get("arguments", "{}")),
                        })
                    anthropic_messages.append({"role": "assistant", "content": content_blocks})
                else:
                    anthropic_messages.append({"role": "assistant", "content": content})
            else:
                anthropic_messages.append({"role": "user", "content": content})

        return "\n\n".join(system_parts), anthropic_messages

    def _convert_tools(self, tools: list[dict] | None) -> list[dict] | None:
        """Convert internal tool format to Anthropic format."""
        if not tools:
            return None
        result = []
        for t in tools:
            func = {k: v for k, v in t.items() if k != "type"}
            result.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return result

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[dict[str, Any], None]:
        system_prompt, anthropic_messages = self._convert_messages(messages)
        anthropic_tools = self._convert_tools(tools)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
        }
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        async with self._client.messages.stream(**kwargs) as stream:
            full_text = ""
            current_tool: dict | None = None

            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        current_tool = {
                            "call_id": block.id,
                            "name": block.name,
                            "arguments": "",
                            "_input": {},
                        }
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        full_text += delta.text
                        yield {"type": "text_delta", "text": delta.text}
                    elif delta.type == "input_json_delta" and current_tool:
                        current_tool["arguments"] += delta.partial_json
                elif event.type == "content_block_stop":
                    if current_tool:
                        yield {
                            "type": "function_call",
                            "call_id": current_tool["call_id"],
                            "name": current_tool["name"],
                            "arguments": current_tool["arguments"] or "{}",
                        }
                        current_tool = None

            # Text done
            if full_text:
                yield {"type": "text_done", "text": full_text}


# ──────────────────────────────────────────────────────────────
# Google Provider (Gemini series)
# ──────────────────────────────────────────────────────────────


class GoogleProvider(LLMProvider):
    """Google Gemini provider — uses the Generative AI API."""

    def __init__(self, api_key: str, base_url: str = ""):
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "google-generativeai package not installed. Run: pip install google-generativeai"
            )
        genai.configure(api_key=api_key)
        self._genai = genai
        self._base_url = base_url

    def _convert_messages(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        """Convert OpenAI-style messages to Gemini format."""
        system_instruction = None
        gemini_messages: list[dict] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_instruction = content if isinstance(content, str) else str(content)
            elif role == "assistant":
                gemini_messages.append({"role": "model", "parts": [content]})
            elif role == "tool":
                # Gemini handles function responses differently
                gemini_messages.append({
                    "role": "function",
                    "parts": [{"function_response": {
                        "name": msg.get("name", "tool"),
                        "response": {"result": content},
                    }}],
                })
            else:
                gemini_messages.append({"role": "user", "parts": [content]})

        return system_instruction, gemini_messages

    def _convert_tools(self, tools: list[dict] | None):
        """Convert internal tool format to Gemini format."""
        if not tools:
            return None
        declarations = []
        for t in tools:
            func = {k: v for k, v in t.items() if k != "type"}
            declarations.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return [self._genai.protos.FunctionDeclaration(**d) for d in declarations]

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[dict[str, Any], None]:
        system_instruction, gemini_messages = self._convert_messages(messages)

        gen_config = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        model_kwargs: dict[str, Any] = {"model_name": model}
        if system_instruction:
            model_kwargs["system_instruction"] = system_instruction

        gemini_tools = self._convert_tools(tools)
        if gemini_tools:
            model_kwargs["tools"] = [gemini_tools]

        gen_model = self._genai.GenerativeModel(**model_kwargs, generation_config=gen_config)

        # Gemini streaming is sync — run in executor
        import asyncio

        full_text = ""

        def _sync_stream():
            return gen_model.generate_content(gemini_messages, stream=True)

        sync_stream = await asyncio.get_event_loop().run_in_executor(None, _sync_stream)

        for chunk in sync_stream:
            if chunk.candidates:
                candidate = chunk.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, "text") and part.text:
                            full_text += part.text
                            yield {"type": "text_delta", "text": part.text}
                        elif hasattr(part, "function_call") and part.function_call:
                            fc = part.function_call
                            yield {
                                "type": "function_call",
                                "call_id": fc.name,  # Gemini doesn't have call IDs
                                "name": fc.name,
                                "arguments": json.dumps(dict(fc.args)) if fc.args else "{}",
                            }

        if full_text:
            yield {"type": "text_done", "text": full_text}


# ──────────────────────────────────────────────────────────────
# Ollama Provider (local models)
# ──────────────────────────────────────────────────────────────


class OllamaProvider(OpenAIProvider):
    """Ollama provider — uses OpenAI-compatible API (default base_url: localhost:11434/v1).

    Ollama's /v1 endpoint is OpenAI-compatible, so we just extend OpenAIProvider
    with a different default base_url and no API key requirement.
    """

    def __init__(self, api_key: str, base_url: str = ""):
        effective_url = base_url or PROVIDER_DEFAULTS["ollama"]["base_url"]
        super().__init__(api_key="ollama", base_url=effective_url)


# ──────────────────────────────────────────────────────────────
# Custom Provider (any OpenAI-compatible API)
# ──────────────────────────────────────────────────────────────


class CustomProvider(OpenAIProvider):
    """Custom provider for any OpenAI-compatible API.

    User must provide base_url + api_key + model.
    """

    def __init__(self, api_key: str, base_url: str):
        if not base_url:
            raise ValueError("llm_base_url is required when llm_provider='custom'")
        super().__init__(api_key=api_key, base_url=base_url)


# ──────────────────────────────────────────────────────────────
# Provider Factory
# ──────────────────────────────────────────────────────────────

# Providers that use the standard OpenAI-compatible path
_OPENAI_COMPATIBLE = {"openai", "dashscope", "zhipu", "moonshot", "deepseek"}


def get_provider(settings: Settings) -> LLMProvider:
    """Factory: return the appropriate LLMProvider based on settings."""
    provider = settings.llm_provider
    api_key = settings.llm_api_key
    base_url = get_provider_base_url(provider, settings.llm_base_url)

    if provider in _OPENAI_COMPATIBLE:
        return OpenAIProvider(api_key=api_key, base_url=base_url)

    if provider == "anthropic":
        return AnthropicProvider(api_key=api_key, base_url=base_url)

    if provider == "google":
        return GoogleProvider(api_key=api_key, base_url=base_url)

    if provider == "ollama":
        return OllamaProvider(api_key=api_key, base_url=base_url)

    if provider == "custom":
        return CustomProvider(api_key=api_key, base_url=base_url)

    # Fallback: treat as OpenAI-compatible
    return OpenAIProvider(api_key=api_key, base_url=base_url)


__all__ = [
    "LLMProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "GoogleProvider",
    "OllamaProvider",
    "CustomProvider",
    "get_provider",
    "get_provider_base_url",
    "PROVIDER_DEFAULTS",
]
