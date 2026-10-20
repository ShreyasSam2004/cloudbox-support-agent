"""Deterministic provider for tests.

A test supplies either a list of responses (consumed in order) or a function that inspects the
request and returns a response. Every request is recorded so tests can assert on what the model
was shown (e.g. that the retrieval evaluation reached the agent).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.common.ids import new_id
from backend.models.base import LLMError, LLMRequest, LLMResponse, ToolCall, Usage

ScriptStep = LLMResponse | Exception | Callable[[LLMRequest], LLMResponse]


def text_response(text: str, *, input_tokens: int = 100, output_tokens: int = 40) -> LLMResponse:
    return LLMResponse(
        text=text,
        stop_reason="end_turn",
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
        model="scripted-model",
        provider="scripted",
    )


def tool_response(*calls: tuple[str, dict[str, Any]], text: str = "") -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=[ToolCall(id=new_id("call"), name=name, arguments=args) for name, args in calls],
        stop_reason="tool_use",
        usage=Usage(input_tokens=100, output_tokens=20),
        model="scripted-model",
        provider="scripted",
    )


class ScriptedProvider:
    name = "scripted"

    def __init__(
        self,
        script: list[ScriptStep] | Callable[[LLMRequest], LLMResponse],
        *,
        model: str = "scripted-model",
    ) -> None:
        self.model = model
        self._script = script
        self._index = 0
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request.model_copy(deep=True))
        if callable(self._script):
            return self._script(request)
        if self._index >= len(self._script):
            raise LLMError("script exhausted", retryable=False, provider=self.name)
        step = self._script[self._index]
        self._index += 1
        if isinstance(step, Exception):
            raise step
        if isinstance(step, LLMResponse):
            return step
        return step(request)

    async def aclose(self) -> None:
        return None
