"""OpenAI Chat Completions provider.

Also works with any OpenAI-compatible endpoint (vLLM, LiteLLM proxy, Azure-compatible gateways)
via ``OPENAI_BASE_URL``.
"""

from __future__ import annotations

import json
import time
from typing import Any

import openai

from backend.models.base import (
    LLMError,
    LLMRequest,
    LLMResponse,
    StopReason,
    TextBlock,
    ToolCall,
    ToolResultBlock,
    Usage,
)

_STOP_REASONS: dict[str, StopReason] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"__invalid_json__": raw[:500]}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


class OpenAIProvider:
    """OpenAI Chat Completions. With an ``AsyncAzureOpenAI`` client this is the Azure OpenAI provider."""

    def __init__(
        self,
        model: str,
        api_key: str | None,
        *,
        base_url: str | None = None,
        timeout_s: float = 90.0,
        max_retries: int = 2,
        client: openai.AsyncOpenAI | None = None,
        name: str = "openai",
    ) -> None:
        self.model = model
        self.name = name
        self._client = client or openai.AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=max_retries
        )

    @staticmethod
    def _messages_to_api(request: LLMRequest) -> list[dict[str, Any]]:
        system = request.system + (f"\n\n{request.system_dynamic}" if request.system_dynamic else "")
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for message in request.messages:
            if message.role == "system":
                out.append({"role": "system", "content": message.text})
                continue
            if message.role == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": message.text or None}
                if message.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                        }
                        for call in message.tool_calls
                    ]
                out.append(entry)
                continue
            # user turn: tool results become `tool` messages, text stays a user message
            texts: list[str] = []
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    out.append({"role": "tool", "tool_call_id": block.tool_call_id, "content": block.content})
                elif isinstance(block, TextBlock) and block.text:
                    texts.append(block.text)
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
        return out

    async def complete(self, request: LLMRequest) -> LLMResponse:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages_to_api(request),
            "max_completion_tokens": request.max_output_tokens,
        }
        if request.tools:
            params["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.input_schema},
                }
                for t in request.tools
            ]
            params["tool_choice"] = request.tool_choice
        if request.response_schema is not None:
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "structured_output", "schema": request.response_schema},
            }

        started = time.perf_counter()
        try:
            response: Any = await self._client.chat.completions.create(**params)
        except openai.RateLimitError as exc:
            raise LLMError(str(exc), retryable=True, provider=self.name, status_code=429) from exc
        except openai.APIStatusError as exc:
            retryable = exc.status_code >= 500 or exc.status_code in (408, 409)
            raise LLMError(
                str(exc), retryable=retryable, provider=self.name, status_code=exc.status_code
            ) from exc
        except openai.APIConnectionError as exc:
            raise LLMError(str(exc), retryable=True, provider=self.name) from exc
        latency_ms = (time.perf_counter() - started) * 1000

        choice = response.choices[0]
        message = choice.message
        tool_calls = [
            ToolCall(id=call.id, name=call.function.name, arguments=_parse_arguments(call.function.arguments))
            for call in (message.tool_calls or [])
            if getattr(call, "function", None) is not None
        ]
        usage = response.usage
        cached = 0
        if usage is not None and getattr(usage, "prompt_tokens_details", None) is not None:
            cached = usage.prompt_tokens_details.cached_tokens or 0
        prompt_tokens = usage.prompt_tokens if usage else 0
        return LLMResponse(
            text=(message.content or "").strip(),
            tool_calls=tool_calls,
            stop_reason=_STOP_REASONS.get(str(choice.finish_reason), "other"),
            usage=Usage(
                input_tokens=max(prompt_tokens - cached, 0),
                output_tokens=usage.completion_tokens if usage else 0,
                cache_read_tokens=cached,
            ),
            model=str(response.model),
            provider=self.name,
            latency_ms=latency_ms,
        )

    async def aclose(self) -> None:
        await self._client.close()
