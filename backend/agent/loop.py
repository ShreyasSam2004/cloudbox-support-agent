"""The agent runtime.

    while not finished and within budget:
        response = model(system, conversation, observations, tools)   # the model chooses
        if response has tool calls: execute them (in parallel) → observations
        else: the model chose to reply → validate → done

Application code never decides *which* tool to call or *whether* to search again. It only:
executes the tools the model asked for, enforces safety boundaries (step / tool-call / wall-clock
budgets), and validates the final reply (citations, disclaimers, redaction). Two bounded guardrails
exist: a one-time "cite your evidence" notice when a reply lacks citations, and a forced
tools-disabled finalization when the step budget runs out.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.agent.context import ContextBuilder
from backend.agent.output import ValidatedOutput, validate_output
from backend.agent.prompts import (
    CITATION_NOTICE_NO_EVIDENCE,
    CITATION_NOTICE_WITH_EVIDENCE,
    FALLBACK_REPLY,
    FINALIZE_NOTICE,
    REFUSAL_REPLY,
    build_session_context,
)
from backend.common.clock import Clock
from backend.common.ids import new_id
from backend.config.settings import Settings
from backend.models.base import ChatMessage, LLMError, LLMProvider, LLMRequest, LLMResponse, Usage
from backend.observability import metrics
from backend.observability.logging import bind_context, get_logger
from backend.observability.recorder import ExecutionRecorder, recording
from backend.schemas.domain import Evidence, SourceOrigin
from backend.schemas.trace import ActivityEvent, AgentTrace
from backend.security.auth import Principal
from backend.storage.sessions import Session
from backend.tools.base import EventSink, ToolBudget, ToolContext
from backend.tools.evidence import EvidenceLedger
from backend.tools.registry import ToolRegistry

log = get_logger(__name__)


@dataclass
class AgentResult:
    execution_id: str
    response_type: str
    answer: str
    sources: list[Evidence]
    activity: list[ActivityEvent]
    trace: AgentTrace
    stop_reason: str
    usage: Usage
    cost_usd: float | None
    latency_ms: float
    evidence_summary: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    retrieved: list[Evidence] = field(default_factory=list)
    """Every evidence item seen during the run (cited or not) — used for retrieval metrics."""


def _total_usage(trace: AgentTrace) -> tuple[Usage, float | None]:
    usage = Usage()
    cost: float | None = 0.0
    for call in trace.llm_calls:
        usage = usage + Usage(
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            cache_read_tokens=call.cache_read_tokens,
            cache_write_tokens=call.cache_write_tokens,
        )
        if call.cost_usd is None and call.stop_reason != "error":
            cost = None
        elif cost is not None and call.cost_usd is not None:
            cost += call.cost_usd
    return usage, cost


class AgentRunner:
    def __init__(
        self,
        llm: LLMProvider,
        registry: ToolRegistry,
        settings: Settings,
        clock: Clock,
        static_prompt: str,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.settings = settings
        self.clock = clock
        self.static_prompt = static_prompt
        self.context_builder = ContextBuilder(max_turns=settings.context_max_turns)

    def _request(
        self, system_dynamic: str, messages: list[ChatMessage], *, tools_enabled: bool
    ) -> LLMRequest:
        return LLMRequest(
            system=self.static_prompt,
            system_dynamic=system_dynamic,
            messages=messages,
            tools=self.registry.specs(),
            tool_choice="auto" if tools_enabled else "none",
            max_output_tokens=self.settings.agent_max_output_tokens,
            effort=self.settings.agent_effort,
            purpose="agent",
        )

    async def run(
        self,
        *,
        session: Session,
        principal: Principal,
        user_message: str,
        request_id: str | None = None,
        emit: EventSink | None = None,
    ) -> AgentResult:
        started = time.perf_counter()
        now = self.clock.now()
        execution_id = new_id("exec")
        bind_context(execution_id=execution_id, session_id=session.session_id, request_id=request_id)

        trace = AgentTrace(
            execution_id=execution_id, session_id=session.session_id, request_id=request_id, started_at=now
        )
        recorder = ExecutionRecorder(trace=trace)
        ledger = EvidenceLedger()
        activity: list[ActivityEvent] = []

        async def sink(event: ActivityEvent) -> None:
            activity.append(event)
            if emit is not None:
                await emit(event)

        ctx = ToolContext(
            execution_id=execution_id,
            session=session,
            principal=principal,
            user_message=user_message,
            ledger=ledger,
            settings=self.settings,
            now=now,
            budget=ToolBudget(max_calls=self.settings.max_tool_calls),
            emit=sink,
        )
        messages, earlier_summary = self.context_builder.build(session, user_message)
        system_dynamic = build_session_context(
            now=now,
            authenticated_customer_id=principal.customer_id if principal.authenticated else None,
            portal_customer_id=session.bound_customer_id if not principal.authenticated else None,
            mentioned_customer_ids=session.mentioned_customer_ids,
            last_account_lookup=session.last_account_lookup,
            earlier_summary=earlier_summary,
        )

        final_text: str | None = None
        stop_reason = "completed"
        guardrail_used = False
        deadline = time.monotonic() + self.settings.agent_timeout_s
        steps = 0

        with recording(recorder):
            await sink(ActivityEvent(kind="thinking", label="Reviewing your request…", at=datetime.now(UTC)))
            for step in range(1, self.settings.max_agent_steps + 1):
                steps = step
                recorder.step = step
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    stop_reason = "timeout"
                    break
                try:
                    response: LLMResponse = await asyncio.wait_for(
                        self.llm.complete(self._request(system_dynamic, messages, tools_enabled=True)),
                        timeout=remaining,
                    )
                except TimeoutError:
                    stop_reason = "timeout"
                    break
                except LLMError as exc:
                    log.error("agent.llm_error", error=str(exc)[:300], retryable=exc.retryable)
                    stop_reason = "llm_error"
                    break

                if response.stop_reason == "refusal":
                    final_text, stop_reason = REFUSAL_REPLY, "refusal"
                    break

                messages.append(response.to_assistant_message())

                if not response.tool_calls:
                    # The model chose to reply. Apply the one-time citation guardrail if needed.
                    draft = validate_output(response.text, ledger)
                    needs_evidence = draft.response_type == "answer" and not draft.has_citations
                    if (
                        needs_evidence
                        and self.settings.citation_guardrail_enabled
                        and not guardrail_used
                        and step < self.settings.max_agent_steps
                    ):
                        guardrail_used = True
                        trace.guardrail_events.append("citation_notice")
                        metrics.GUARDRAIL_EVENTS.labels("citation_notice").inc()
                        await sink(
                            ActivityEvent(
                                kind="guardrail", label="Double-checking sources…", at=datetime.now(UTC)
                            )
                        )
                        notice = CITATION_NOTICE_WITH_EVIDENCE if len(ledger) else CITATION_NOTICE_NO_EVIDENCE
                        messages.append(ChatMessage.system_notice(notice))
                        continue
                    final_text = response.text
                    break

                executions = await asyncio.gather(
                    *(self.registry.execute(call, ctx, step) for call in response.tool_calls)
                )
                trace.tool_calls.extend(record for _, record in executions)
                messages.append(ChatMessage.tool_results([block for block, _ in executions]))
            else:
                stop_reason = "max_steps"

            if final_text is None and stop_reason in ("max_steps", "timeout"):
                # Safety boundary reached: one last call with tools disabled.
                trace.guardrail_events.append(f"forced_finalization:{stop_reason}")
                metrics.GUARDRAIL_EVENTS.labels("forced_finalization").inc()
                messages.append(ChatMessage.system_notice(FINALIZE_NOTICE))
                try:
                    response = await asyncio.wait_for(
                        self.llm.complete(self._request(system_dynamic, messages, tools_enabled=False)),
                        timeout=max(self.settings.llm_timeout_s, 30.0),
                    )
                    final_text = response.text or None
                except (LLMError, TimeoutError):
                    final_text = None

        validated = validate_output(final_text or FALLBACK_REPLY, ledger)
        if final_text is None:
            validated.warnings.append("fallback_reply")
        return self._finish(
            execution_id=execution_id,
            trace=trace,
            ledger=ledger,
            validated=validated,
            activity=activity,
            stop_reason=stop_reason,
            steps=steps,
            started=started,
            session=session,
        )

    # ------------------------------------------------------------------ finalization

    def _finish(
        self,
        *,
        execution_id: str,
        trace: AgentTrace,
        ledger: EvidenceLedger,
        validated: ValidatedOutput,
        activity: list[ActivityEvent],
        stop_reason: str,
        steps: int,
        started: float,
        session: Session,
    ) -> AgentResult:
        latency_ms = (time.perf_counter() - started) * 1000
        sources = [e for eid in validated.cited_ids if (e := ledger.get(eid)) is not None]
        kb_searches = [c for c in trace.tool_calls if c.tool == "search_knowledge_base" and c.status == "ok"]
        verdicts = [
            {
                "query": c.arguments.get("query"),
                "relevant": (c.retrieval_verdict or {}).get("relevant"),
                "confidence": (c.retrieval_verdict or {}).get("confidence"),
            }
            for c in kb_searches
        ]
        counts = {origin.value: 0 for origin in SourceOrigin}
        for source in sources:
            counts[source.origin.value] += 1

        grounded = validated.response_type != "answer" or bool(sources)
        best_kb_confidence = max((v["confidence"] or 0.0 for v in verdicts if v["relevant"]), default=0.0)
        if validated.response_type != "answer":
            confidence = "low" if validated.response_type == "cannot_verify" else "medium"
        elif (
            counts[SourceOrigin.INTERNAL_KB.value]
            and best_kb_confidence >= 0.6
            and not validated.invalid_citations
        ):
            confidence = "high"
        elif sources:
            confidence = "medium"
        else:
            confidence = "low"

        evidence_summary: dict[str, Any] = {
            "grounded": grounded,
            "confidence": confidence,
            "retrieval_attempts": len([c for c in trace.tool_calls if c.tool == "search_knowledge_base"]),
            "retrieval_evaluations": verdicts,
            "web_search_used": any(c.tool == "web_search" for c in trace.tool_calls),
            "account_data_used": any(
                c.tool == "get_customer_account" and c.status == "ok" for c in trace.tool_calls
            ),
            "sources_cited": counts,
            "invalid_citations_removed": len(validated.invalid_citations),
        }

        trace.finished_at = datetime.now(UTC)
        trace.stop_reason = stop_reason
        trace.response_type = validated.response_type
        trace.cited_evidence_ids = validated.cited_ids
        usage, cost = _total_usage(trace)

        final_label = {
            "answer": f"Answer generated from {len(sources)} source{'s' if len(sources) != 1 else ''}.",
            "clarification": "Asked you a clarifying question.",
            "cannot_verify": "Could not verify an answer from available sources.",
        }[validated.response_type]
        activity.append(ActivityEvent(kind="final", label=final_label, at=datetime.now(UTC)))

        session.add_assistant_turn(
            validated.text, validated.response_type, list(dict.fromkeys(s.title for s in sources))
        )

        metrics.AGENT_RUNS.labels(stop_reason, validated.response_type).inc()
        metrics.AGENT_STEPS.observe(steps)
        metrics.AGENT_LATENCY.observe(latency_ms / 1000)
        metrics.RETRIEVAL_ATTEMPTS.observe(evidence_summary["retrieval_attempts"])
        log.info(
            "agent.completed",
            stop_reason=stop_reason,
            response_type=validated.response_type,
            steps=steps,
            trajectory=trace.trajectory(),
            tool_calls=len(trace.tool_calls),
            retrieval_attempts=evidence_summary["retrieval_attempts"],
            web_search_used=evidence_summary["web_search_used"],
            llm_calls=len(trace.llm_calls),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost,
            latency_ms=round(latency_ms, 1),
            grounded=grounded,
            warnings=validated.warnings,
        )
        return AgentResult(
            execution_id=execution_id,
            response_type=validated.response_type,
            answer=validated.text,
            sources=sources,
            activity=activity,
            trace=trace,
            stop_reason=stop_reason,
            usage=usage,
            cost_usd=cost,
            latency_ms=latency_ms,
            evidence_summary=evidence_summary,
            warnings=validated.warnings,
            retrieved=ledger.all(),
        )
