"""Domain models shared by retrieval, tools, the agent and the API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceOrigin(StrEnum):
    INTERNAL_KB = "internal_kb"
    PUBLIC_WEB = "public_web"
    CUSTOMER_ACCOUNT = "customer_account"


# --------------------------------------------------------------------------- knowledge base


class DocumentRecord(BaseModel):
    doc_id: str
    title: str
    doc_type: str
    source_path: str
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkRecord(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    section_path: str
    content: str
    """Original markdown shown to the model and the UI."""
    embedding_text: str
    """Text that was embedded/indexed (breadcrumb + content + linearised tables)."""
    ordinal: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScoredChunk(BaseModel):
    chunk: ChunkRecord
    score: float
    """Fused relevance score (RRF in hybrid mode, cosine similarity in vector mode)."""
    vector_score: float | None = None
    lexical_score: float | None = None


class MetadataFilter(BaseModel):
    doc_ids: list[str] | None = None
    doc_types: list[str] | None = None

    def is_empty(self) -> bool:
        return not self.doc_ids and not self.doc_types


class RetrievalResult(BaseModel):
    query: str
    chunks: list[ScoredChunk]
    mode: str
    latency_ms: float


class RetrievalVerdict(BaseModel):
    """Structured output of the LLM retrieval evaluator."""

    relevant: bool | None
    confidence: float = Field(ge=0.0, le=1.0)
    coverage: Literal["full", "partial", "none", "unknown"] = "unknown"
    useful_evidence_ids: list[str] = Field(default_factory=list)
    passage_scores: dict[str, int] = Field(default_factory=dict)
    """Per-passage relevance 0-3, keyed by the label the evaluator saw (used for re-ranking)."""
    missing_information: str = ""
    reason: str = ""
    evaluator_status: Literal["ok", "disabled", "error"] = "ok"


# --------------------------------------------------------------------------- evidence


class Evidence(BaseModel):
    """One citable item the agent has seen during a run (KB chunk, web page, account record)."""

    evidence_id: str
    origin: SourceOrigin
    title: str
    snippet: str
    doc_id: str | None = None
    section: str | None = None
    url: str | None = None
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: str = Field(default="", exclude=True, repr=False)
    """Full text the agent saw, for offline grading (LLM judge). Never serialized."""


# --------------------------------------------------------------------------- customers


class Charge(BaseModel):
    charge_id: str
    created_at: datetime
    amount_usd: float
    status: Literal["succeeded", "pending", "refunded", "failed"]
    kind: Literal["subscription", "renewal", "authorization_hold", "add_on", "proration"] = "subscription"
    invoice_id: str | None = None
    description: str = ""


class Subscription(BaseModel):
    plan: Literal["free", "starter", "pro", "business", "enterprise"]
    billing_cycle: Literal["monthly", "annual", "none"]
    status: Literal["active", "trialing", "past_due", "canceled", "suspended"]
    seats: int = 1
    price_usd: float = 0.0
    started_at: datetime
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    renewal_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    cancel_effective_at: datetime | None = None
    trial_ends_at: datetime | None = None
    payment_method_on_file: bool = True
    payment_failure: dict[str, Any] | None = None
    add_ons: list[str] = Field(default_factory=list)


class Usage(BaseModel):
    api_requests_this_period: int = 0
    api_monthly_quota: int = 0
    rate_limit_per_min: int = 0
    peak_requests_per_min_24h: int = 0
    http_429_last_24h: int = 0
    http_429_breakdown: dict[str, int] = Field(default_factory=dict)
    storage_used_gb: float = 0.0
    storage_limit_gb: float = 0.0
    usage_since_last_renewal: dict[str, int] = Field(default_factory=dict)


class SecurityStatus(BaseModel):
    account_status: Literal["active", "locked", "suspended"] = "active"
    locked_reason: str | None = None
    failed_login_attempts_24h: int = 0
    lockouts_24h: int = 0
    two_factor_enabled: bool = False
    sso_enforced: bool = False


class Contract(BaseModel):
    contract_id: str
    term_start: datetime
    term_end: datetime
    annual_value_usd: float
    notice_period_days: int
    account_manager: str


class CustomerAccount(BaseModel):
    customer_id: str
    organization_name: str
    contact_name: str
    contact_email: str
    contact_role: str
    subscription: Subscription
    charges: list[Charge] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    security: SecurityStatus = Field(default_factory=SecurityStatus)
    contract: Contract | None = None
    notes: list[str] = Field(default_factory=list)
