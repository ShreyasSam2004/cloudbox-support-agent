"""Public API contract (request/response models)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.domain import Evidence, SourceOrigin
from backend.schemas.trace import ActivityEvent

ORIGIN_LABELS = {
    SourceOrigin.INTERNAL_KB: "CloudBox knowledge base",
    SourceOrigin.PUBLIC_WEB: "Public web — not CloudBox policy",
    SourceOrigin.CUSTOMER_ACCOUNT: "Your account",
}


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    customer_id: str | None = Field(default=None, pattern=r"^[Cc]\d{3,6}$")
    message: str = Field(min_length=1, max_length=4000)


class SourceOut(BaseModel):
    evidence_id: str
    origin: SourceOrigin
    label: str
    title: str
    section: str | None = None
    url: str | None = None
    snippet: str
    doc_id: str | None = None

    @classmethod
    def from_evidence(cls, evidence: Evidence) -> SourceOut:
        snippet = (
            evidence.snippet if evidence.origin != SourceOrigin.CUSTOMER_ACCOUNT else evidence.snippet[:120]
        )
        return cls(
            evidence_id=evidence.evidence_id,
            origin=evidence.origin,
            label=ORIGIN_LABELS[evidence.origin],
            title=evidence.title,
            section=evidence.section,
            url=evidence.url,
            snippet=snippet,
            doc_id=evidence.doc_id,
        )


class ToolCallOut(BaseModel):
    step: int
    tool: str
    status: str
    latency_ms: float
    attempts: int
    summary: str
    query: str | None = None


class UsageOut(BaseModel):
    llm_calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    estimated_cost_usd: float | None
    latency_ms: float


class ChatResponse(BaseModel):
    request_id: str
    session_id: str
    execution_id: str
    response_type: Literal["answer", "clarification", "cannot_verify"]
    answer: str
    sources: list[SourceOut]
    activity: list[ActivityEvent]
    tool_calls: list[ToolCallOut]
    evidence: dict[str, Any]
    usage: UsageOut
    stop_reason: str
    warnings: list[str] = Field(default_factory=list)


class SessionTurnOut(BaseModel):
    role: str
    content: str
    response_type: str | None = None
    source_titles: list[str] = Field(default_factory=list)


class SessionOut(BaseModel):
    session_id: str
    customer_id: str | None
    turns: list[SessionTurnOut]


class ErrorOut(BaseModel):
    error: str
    message: str
    request_id: str | None = None
