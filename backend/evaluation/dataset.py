"""Benchmark dataset schema and loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Behavior = Literal["answer", "clarify", "cannot_verify", "cannot_verify_or_answer", "refuse"]


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class EvalCase(BaseModel):
    id: str
    category: str
    question: str
    customer_id: str | None = None
    history: list[HistoryTurn] = Field(default_factory=list)
    expected_behavior: Behavior
    required_facts: list[list[str]] = Field(default_factory=list)
    """Each inner list is a group of acceptable alternatives (case-insensitive regex); every group must match."""
    forbidden_facts: list[str] = Field(default_factory=list)
    """Case-insensitive regexes that indicate a hallucinated or unsafe answer."""
    relevant_doc_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    """Verbatim knowledge-base phrases a correct answer needs (retrieval benchmark ground truth)."""
    requires_account: bool = False
    requires_web: bool = False
    reference_answer: str = ""


def load_dataset(
    path: Path, *, ids: list[str] | None = None, categories: list[str] | None = None
) -> list[EvalCase]:
    cases = [
        EvalCase.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if ids:
        cases = [c for c in cases if c.id in ids]
    if categories:
        cases = [c for c in cases if c.category in categories]
    return cases
