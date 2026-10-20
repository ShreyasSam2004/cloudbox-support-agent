"""Anthropic Messages API provider (official ``anthropic`` SDK, async client).

Notes on current-model behaviour that this adapter accounts for:

* Claude 5.x models think adaptively by default; we never send ``thinking`` and control depth
  with ``output_config.effort``. Thinking blocks returned inside an agent loop are replayed
  *unchanged* (``provider_raw``), which the API requires.
* Forced ``tool_choice`` (``any``/``tool``) is rejected on the newest models, so the agent only
  uses ``auto`` and ``none`` (the latter for forced finalization at the step limit).
* The static system prompt carries a ``cache_control`` breakpoint; tools render before system, so
  tools + static prompt are cached together. Volatile per-request context goes in a second,
  uncached system block.
* Server-side refusal fallback (``fallbacks: "default"``) is enabled by default where supported.
"""

from __future__ import annotations

import time
from typing import Any

import anthropic

from backend.models.base import (
    ChatMessage,
    LLMError,
    LLMRequest,
    LLMResponse,
    StopReason,
    TextBlock,
    ToolCall,
    ToolResultBlock,
    Usage,
)

_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5")
_MID_CONVERSATION_SYSTEM_MODELS = (
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-fable-5",
    "claude-mythos-5",
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
)
_EFFORT_MODELS = (
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-fable-5",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-haiku-5-5",
)

_STOP_REASONS: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "stop_sequence": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


def _supports(model: str, prefixes: tuple[str, ...]) -> bool:
    return model.startswith(prefixes)


class AnthropicProvider:
    """Claude via the first-party API (``platform="anthropic"``) or Microsoft Foundry (``"foundry"``).

    On Foundry the same Messages API is served at ``https://<resource>.services.ai.azure.com/anthropic/``
    and authenticated with Entra ID (managed identity). Foundry does not offer server-side refusal
    fallback or mid-conversation system messages, so both are disabled there.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        *,
        platform: str = "anthropic",
        timeout_s: float = 90.0,
        max_retries: int = 2,
        refusal_fallback: bool = True,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.name = "anthropic" if platform == "anthropic" else "anthropic_foundry"
        # api_key=None lets the SDK resolve credentials itself (env var, `ant auth login` profile, WIF).
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout_s, max_retries=max_retries
        )
        first_party = platform == "anthropic"
        self._use_fallback = first_party and refusal_fallback and _supports(model, _FALLBACK_MODELS)
        self._mid_system = first_party and _supports(model, _MID_CONVERSATION_SYSTEM_MODELS)

    # ------------------------------------------------------------------ translation

    def _message_to_api(self, message: ChatMessage, previous_role: str | None) -> dict[str, Any]:
        if message.role == "assistant" and message.provider_raw and message.provider_name == self.name:
            return {"role": "assistant", "content": message.provider_raw}
        if message.role == "system":
            # A mid-conversation system message must follow a user turn; elsewhere (or on platforms
            # without support) the operator notice is sent as a clearly labelled user turn.
            if self._mid_system and previous_role == "user":
                return {"role": "system", "content": message.text}
            return {"role": "user", "content": f"[CloudBox platform notice] {message.text}"}

        content: list[dict[str, Any]] = []
        for block in message.content:
            if isinstance(block, TextBlock):
                if block.text:
                    content.append({"type": "text", "text": block.text})
            elif isinstance(block, ToolCall):
                content.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.arguments}
                )
            elif isinstance(block, ToolResultBlock):
                content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.tool_call_id,
                        "content": block.content,
                        "is_error": block.is_error,
                    }
                )
        if not content:
            content.append({"type": "text", "text": "(empty)"})
        return {"role": message.role, "content": content}

    def _build_params(self, request: LLMRequest) -> dict[str, Any]:
        system: list[dict[str, Any]] = [
            {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}
        ]
        if request.system_dynamic:
            system.append({"type": "text", "text": request.system_dynamic})

        api_messages: list[dict[str, Any]] = []
        for message in request.messages:
            previous = api_messages[-1]["role"] if api_messages else None
            api_messages.append(self._message_to_api(message, previous))
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_output_tokens,
            "system": system,
            "messages": api_messages,
        }
        if request.tools:
            params["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in request.tools
            ]
            params["tool_choice"] = {"type": request.tool_choice}

        output_config: dict[str, Any] = {}
        if request.effort and _supports(self.model, _EFFORT_MODELS):
            output_config["effort"] = request.effort
        if request.response_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": request.response_schema}
        if output_config:
            params["output_config"] = output_config
        return params

    # ------------------------------------------------------------------ call

    async def complete(self, request: LLMRequest) -> LLMResponse:
        params = self._build_params(request)
        started = time.perf_counter()
        try:
            if self._use_fallback:
                response: Any = await self._client.beta.messages.create(
                    **params, betas=[_FALLBACK_BETA], fallbacks="default"
                )
            else:
                response = await self._client.messages.create(**params)
        except anthropic.RateLimitError as exc:
            raise LLMError(str(exc), retryable=True, provider=self.name, status_code=429) from exc
        except anthropic.APIStatusError as exc:
            retryable = exc.status_code >= 500 or exc.status_code in (408, 409)
            raise LLMError(
                str(exc), retryable=retryable, provider=self.name, status_code=exc.status_code
            ) from exc
        except anthropic.APIConnectionError as exc:  # includes timeouts
            raise LLMError(str(exc), retryable=True, provider=self.name) from exc
        latency_ms = (time.perf_counter() - started) * 1000

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {})))

        usage = response.usage
        return LLMResponse(
            text="".join(text_parts).strip(),
            tool_calls=tool_calls,
            stop_reason=_STOP_REASONS.get(str(response.stop_reason), "other"),
            usage=Usage(
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            ),
            model=str(response.model),
            provider=self.name,
            latency_ms=latency_ms,
            raw_assistant_content=[block.to_dict(mode="json") for block in response.content],
        )

    async def aclose(self) -> None:
        await self._client.close()
