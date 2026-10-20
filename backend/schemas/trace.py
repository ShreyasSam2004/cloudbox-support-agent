"""Execution trace records.

A trace captures *what the agent did* (model calls, tool calls, observations summaries, usage),
never hidden reasoning. It is safe to persist and to show to operators.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class LLMCallRecord(BaseModel):
    step: int
    purpose: str
    provider: str
    model: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None
    stop_reason: str
    requested_tools: list[str] = Field(default_factory=list)
    error: str | None = None


class ToolCallRecord(BaseModel):
    step: int
    call_id: str
    tool: str
    arguments: dict[str, Any]
    status: Literal["ok", "error"]
    latency_ms: float
    attempts: int = 1
    summary: str = ""
    error_code: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    retrieval_verdict: dict[str, Any] | None = None


class ActivityEvent(BaseModel):
    """User-safe, high-level progress event ("Searching CloudBox knowledge base…")."""

    kind: Literal["thinking", "tool_started", "tool_finished", "guardrail", "final"]
    label: str
    tool: str | None = None
    detail: str | None = None
    at: datetime


class AgentTrace(BaseModel):
    execution_id: str
    session_id: str
    request_id: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    llm_calls: list[LLMCallRecord] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    guardrail_events: list[str] = Field(default_factory=list)
    stop_reason: str | None = None
    response_type: str | None = None
    cited_evidence_ids: list[str] = Field(default_factory=list)

    def trajectory(self) -> list[str]:
        """Ordered action list, e.g. ``["search_knowledge_base", "get_customer_account", "answer"]``."""
        names = [call.tool for call in sorted(self.tool_calls, key=lambda c: c.step)]
        if self.response_type:
            names.append(self.response_type)
        return names
