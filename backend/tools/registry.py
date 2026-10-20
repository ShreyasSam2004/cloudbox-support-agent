"""Tool registry: the single choke point between the model and side effects.

For every tool call it enforces, in order: known tool → tool-call budget → schema validation →
execution with timeout and retry/backoff (transient errors only) → error normalisation → tracing,
metrics and user-safe activity events. The model always receives an observation, never an exception.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from backend.common.retry import RetryPolicy, retry_async
from backend.models.base import ToolCall, ToolResultBlock, ToolSpec
from backend.observability import metrics
from backend.observability.logging import get_logger
from backend.schemas.trace import ActivityEvent, ToolCallRecord
from backend.tools.base import Tool, ToolContext, ToolError, ToolOutput

log = get_logger(__name__)


def _render(observation: dict[str, Any]) -> str:
    return json.dumps(observation, ensure_ascii=False, default=str)


def _error_observation(code: str, message: str, retryable: bool) -> dict[str, Any]:
    return {"status": "error", "error": {"code": code, "message": message, "retryable": retryable}}


def _safe_args(arguments: dict[str, Any]) -> dict[str, Any]:
    """Arguments as recorded in traces/logs (truncated; no free-form blobs)."""
    out: dict[str, Any] = {}
    for key, value in list(arguments.items())[:8]:
        out[key] = value[:200] if isinstance(value, str) else value
    return out


class ToolRegistry:
    def __init__(self, tools: list[Tool], *, default_timeout_s: float = 30.0, max_attempts: int = 3) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._default_timeout_s = default_timeout_s
        self._retry = RetryPolicy(max_attempts=max_attempts, base_delay_s=0.3, max_delay_s=3.0)

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[ToolSpec]:
        # Deterministic order keeps the prompt-cache prefix stable.
        return [self._tools[name].spec() for name in sorted(self._tools)]

    async def _emit(self, ctx: ToolContext, event: ActivityEvent) -> None:
        if ctx.emit is not None:
            await ctx.emit(event)

    async def execute(
        self, call: ToolCall, ctx: ToolContext, step: int
    ) -> tuple[ToolResultBlock, ToolCallRecord]:
        started = time.perf_counter()
        tool = self._tools.get(call.name)
        attempts = 0
        output: ToolOutput | None = None
        error: tuple[str, str, bool] | None = None

        if tool is None:
            error = (
                "unknown_tool",
                f"No tool named {call.name!r}. Available tools: {', '.join(self.names)}.",
                False,
            )
        elif ctx.budget.exhausted:
            error = (
                "tool_budget_exhausted",
                "The tool-call budget for this request is used up. Answer with the evidence you already have, "
                "or tell the customer what you could not verify.",
                False,
            )
        else:
            ctx.budget.used += 1
            try:
                args = tool.input_model.model_validate(call.arguments)
            except ValidationError as exc:
                problems = "; ".join(
                    f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg']}" for e in exc.errors()[:5]
                )
                error = ("invalid_arguments", f"Invalid arguments for {tool.name}: {problems}", False)
            else:
                await self._emit(
                    ctx,
                    ActivityEvent(
                        kind="tool_started", label=tool.activity_label, tool=tool.name, at=datetime.now(UTC)
                    ),
                )
                timeout = tool.timeout_s or self._default_timeout_s

                tried = [0]

                async def _attempt(tool: Tool = tool, args: Any = args) -> ToolOutput:
                    tried[0] += 1
                    return await asyncio.wait_for(tool.run(args, ctx), timeout=timeout)

                def _retryable(exc: BaseException) -> bool:
                    return isinstance(exc, TimeoutError) or (isinstance(exc, ToolError) and exc.retryable)

                def _on_retry(attempt: int, exc: BaseException, delay: float, name: str = tool.name) -> None:
                    log.warning(
                        "tool.retry",
                        tool=name,
                        attempt=attempt,
                        error=type(exc).__name__,
                        delay_s=round(delay, 2),
                    )

                try:
                    output, attempts = await retry_async(_attempt, self._retry, _retryable, _on_retry)
                except TimeoutError:
                    error = ("timeout", f"{tool.name} timed out after {timeout:.0f}s.", True)
                except ToolError as exc:
                    error = (exc.code, exc.message, exc.retryable)
                except Exception:  # unexpected bug in a tool: never leak details to the model
                    log.exception("tool.unexpected_error", tool=tool.name)
                    error = ("internal_error", f"{tool.name} failed unexpectedly.", False)
                attempts = tried[0]

        latency_ms = (time.perf_counter() - started) * 1000
        status = "ok" if output is not None else "error"
        metrics.TOOL_CALLS.labels(call.name if tool else "unknown", status).inc()
        metrics.TOOL_LATENCY.labels(call.name if tool else "unknown").observe(latency_ms / 1000)

        if output is not None:
            observation = {"status": "ok", **output.observation}
            summary = output.summary
        else:
            assert error is not None
            observation = _error_observation(*error)
            summary = f"error: {error[0]}"

        record = ToolCallRecord(
            step=step,
            call_id=call.id,
            tool=call.name,
            arguments=_safe_args(call.arguments),
            status=status,
            latency_ms=latency_ms,
            attempts=max(attempts, 1) if tool else 0,
            summary=summary,
            error_code=error[0] if error else None,
            evidence_ids=output.evidence_ids if output else [],
            retrieval_verdict=output.verdict.model_dump() if output and output.verdict else None,
        )
        log.info(
            "tool.call",
            tool=call.name,
            step=step,
            status=status,
            latency_ms=round(latency_ms, 1),
            attempts=record.attempts,
            error_code=record.error_code,
            evidence=len(record.evidence_ids),
        )
        if tool is not None:
            await self._emit(
                ctx,
                ActivityEvent(
                    kind="tool_finished",
                    label=tool.activity_label.rstrip("…."),
                    tool=tool.name,
                    detail=summary,
                    at=datetime.now(UTC),
                ),
            )
        result = ToolResultBlock(
            tool_call_id=call.id, name=call.name, content=_render(observation), is_error=output is None
        )
        return result, record
