"""Local models through Ollama's native ``/api/chat`` endpoint.

The native API (rather than Ollama's OpenAI-compatible shim) is used because it exposes
``options.num_ctx`` — the default context window silently truncates long agent prompts — and the
``think`` switch for reasoning models.

Small local models sometimes emit a tool call as a JSON object in plain text instead of the
structured ``tool_calls`` field. :func:`_recover_text_tool_call` recovers exactly that shape, and
only for tool names that were actually offered, so the agent loop sees a normal tool call.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from backend.common.ids import new_id
from backend.common.retry import RetryPolicy, retry_async
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

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _recover_text_tool_call(text: str, tool_names: set[str]) -> ToolCall | None:
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    name = payload.get("name") or payload.get("tool") or payload.get("function")
    args = payload.get("arguments", payload.get("parameters", {}))
    if isinstance(name, str) and name in tool_names and isinstance(args, dict):
        return ToolCall(id=new_id("call"), name=name, arguments=args)
    return None


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://localhost:11434",
        num_ctx: int = 8192,
        keep_alive: str = "30m",
        think: bool | None = None,
        timeout_s: float = 300.0,
        max_attempts: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._num_ctx = num_ctx
        self._keep_alive = keep_alive
        self._think = think
        self._retry = RetryPolicy(max_attempts=max_attempts, base_delay_s=1.0, max_delay_s=8.0)
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout_s)

    @staticmethod
    def _messages_to_api(request: LLMRequest) -> list[dict[str, Any]]:
        system = request.system + (f"\n\n{request.system_dynamic}" if request.system_dynamic else "")
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for message in request.messages:
            if message.role == "system":
                out.append({"role": "system", "content": message.text})
            elif message.role == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": message.text}
                if message.tool_calls:
                    entry["tool_calls"] = [
                        {"function": {"name": c.name, "arguments": c.arguments}} for c in message.tool_calls
                    ]
                out.append(entry)
            else:
                texts: list[str] = []
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        out.append({"role": "tool", "content": block.content, "tool_name": block.name})
                    elif isinstance(block, TextBlock) and block.text:
                        texts.append(block.text)
                if texts:
                    out.append({"role": "user", "content": "\n".join(texts)})
        return out

    async def complete(self, request: LLMRequest) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages_to_api(request),
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {"num_ctx": self._num_ctx, "temperature": 0, "num_predict": request.max_output_tokens},
        }
        offered = {t.name for t in request.tools} if request.tool_choice == "auto" else set()
        if offered:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.input_schema},
                }
                for t in request.tools
            ]
        if request.response_schema is not None:
            payload["format"] = request.response_schema
        if self._think is not None:
            payload["think"] = self._think

        async def _call() -> dict[str, Any]:
            response = await self._client.post("/api/chat", json=payload)
            if response.status_code >= 400:
                raise LLMError(
                    f"ollama HTTP {response.status_code}: {response.text[:300]}",
                    retryable=response.status_code >= 500,
                    provider=self.name,
                    status_code=response.status_code,
                )
            data: dict[str, Any] = response.json()
            return data

        def _retryable(exc: BaseException) -> bool:
            return isinstance(exc, httpx.TransportError) or (isinstance(exc, LLMError) and exc.retryable)

        started = time.perf_counter()
        try:
            data, _ = await retry_async(_call, self._retry, _retryable)
        except httpx.HTTPError as exc:
            raise LLMError(f"ollama transport error: {exc!r}", retryable=True, provider=self.name) from exc
        latency_ms = (time.perf_counter() - started) * 1000

        message = data.get("message") or {}
        text = _THINK_RE.sub("", message.get("content") or "").strip()
        tool_calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            fn = raw.get("function") or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"__invalid_json__": args[:500]}
            tool_calls.append(
                ToolCall(id=raw.get("id") or new_id("call"), name=fn.get("name", ""), arguments=args)
            )
        if not tool_calls and offered and text:
            recovered = _recover_text_tool_call(text, offered)
            if recovered is not None:
                tool_calls, text = [recovered], ""

        stop: StopReason = "tool_use" if tool_calls else "end_turn"
        if data.get("done_reason") == "length":
            stop = "max_tokens"
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=stop,
            usage=Usage(
                input_tokens=int(data.get("prompt_eval_count") or 0),
                output_tokens=int(data.get("eval_count") or 0),
            ),
            model=self.model,
            provider=self.name,
            latency_ms=latency_ms,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
