"""Decorator provider that meters every model call (latency, tokens, cost, errors)."""

from __future__ import annotations

import asyncio
import time

from backend.config.pricing import estimate_cost_usd
from backend.models.base import LLMError, LLMProvider, LLMRequest, LLMResponse
from backend.observability import metrics
from backend.observability.logging import get_logger
from backend.observability.recorder import current_recorder
from backend.schemas.trace import LLMCallRecord

log = get_logger(__name__)


class MeteredLLM:
    def __init__(self, inner: LLMProvider) -> None:
        self.inner = inner
        self.name = inner.name
        self.model = inner.model

    async def complete(self, request: LLMRequest) -> LLMResponse:
        recorder = current_recorder()
        step = recorder.step if recorder else 0
        started = time.perf_counter()
        try:
            response = await self.inner.complete(request)
        except asyncio.CancelledError:
            # The caller's deadline cancelled the call: record it so timeouts are visible in traces.
            metrics.LLM_CALLS.labels(self.name, self.model, request.purpose, "cancelled").inc()
            if recorder:
                recorder.add_llm_call(
                    LLMCallRecord(
                        step=step,
                        purpose=request.purpose,
                        provider=self.name,
                        model=self.model,
                        latency_ms=(time.perf_counter() - started) * 1000,
                        input_tokens=0,
                        output_tokens=0,
                        stop_reason="cancelled",
                        error="deadline_exceeded",
                    )
                )
            raise
        except LLMError as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            metrics.LLM_CALLS.labels(self.name, self.model, request.purpose, "error").inc()
            log.warning(
                "llm.call_failed",
                provider=self.name,
                model=self.model,
                purpose=request.purpose,
                retryable=exc.retryable,
                status_code=exc.status_code,
                latency_ms=round(latency_ms, 1),
            )
            if recorder:
                recorder.add_llm_call(
                    LLMCallRecord(
                        step=step,
                        purpose=request.purpose,
                        provider=self.name,
                        model=self.model,
                        latency_ms=latency_ms,
                        input_tokens=0,
                        output_tokens=0,
                        stop_reason="error",
                        error=type(exc).__name__,
                    )
                )
            raise

        usage = response.usage
        cost = estimate_cost_usd(
            self.name,
            self.model,
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_tokens,
            usage.cache_write_tokens,
        )
        metrics.LLM_CALLS.labels(self.name, self.model, request.purpose, "ok").inc()
        metrics.LLM_LATENCY.labels(self.name, request.purpose).observe(response.latency_ms / 1000)
        for kind, value in (
            ("input", usage.input_tokens),
            ("output", usage.output_tokens),
            ("cache_read", usage.cache_read_tokens),
            ("cache_write", usage.cache_write_tokens),
        ):
            if value:
                metrics.LLM_TOKENS.labels(self.model, request.purpose, kind).inc(value)
        if cost:
            metrics.LLM_COST.labels(self.model, request.purpose).inc(cost)

        log.info(
            "llm.call",
            provider=self.name,
            model=self.model,
            purpose=request.purpose,
            step=step,
            latency_ms=round(response.latency_ms, 1),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            stop_reason=response.stop_reason,
            tool_calls=[c.name for c in response.tool_calls],
            cost_usd=cost,
        )
        if recorder:
            recorder.add_llm_call(
                LLMCallRecord(
                    step=step,
                    purpose=request.purpose,
                    provider=self.name,
                    model=self.model,
                    latency_ms=response.latency_ms,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    cache_write_tokens=usage.cache_write_tokens,
                    cost_usd=cost,
                    stop_reason=response.stop_reason,
                    requested_tools=[c.name for c in response.tool_calls],
                )
            )
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()
