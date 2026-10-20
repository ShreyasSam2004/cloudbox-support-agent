"""Deterministic grading.

Each case is graded from the final answer text, the response type, the citations and the
execution trace. No model is involved, so results are reproducible and cost nothing to recompute.

Definitions (also in docs/evaluation.md):

* **behavior_ok** — the system did the expected kind of thing (answered / asked a clarifying
  question / declined to assert unverifiable facts / refused).
* **fact_recall** — share of required fact groups present in the answer.
* **correct** — behavior_ok, every required fact group present, and no forbidden statement.
* **hallucinated** — a forbidden statement appeared, or the answer cited evidence that was never retrieved.
* **grounded** — non-answers, or answers whose citations all resolve to retrieved evidence (≥1 citation).
* **resolved** — correct and not hallucinated (the headline "would this have resolved the ticket" metric).
* **retrieval_recall** — share of the case's relevant documents that were retrieved at any point.
"""

from __future__ import annotations

import re
import statistics
from typing import Any

from pydantic import BaseModel, Field

from backend.evaluation.dataset import EvalCase

_ABSTAIN_RE = re.compile(
    r"can(?:no|')t (?:verify|confirm|find)|unable to (?:verify|confirm|find)|(?:do|does)n'?t (?:have|mention|cover|include|list)|"
    r"not (?:documented|covered|mentioned|listed|able to (?:verify|confirm))|no (?:information|documentation|mention)|"
    r"isn't (?:documented|covered|mentioned)|is not (?:documented|covered|mentioned)",
    re.I,
)
_REFUSAL_RE = re.compile(
    r"can(?:no|')t (?:share|provide|show|reveal|disclose|help with)|unable to (?:share|provide|show|reveal)|"
    r"not able to (?:share|provide|show|reveal)|only (?:discuss|access|help with|share)|won'?t (?:share|reveal)",
    re.I,
)


class CaseResult(BaseModel):
    case_id: str
    category: str
    system: str
    response_type: str
    answer: str
    cited_ids: list[str] = Field(default_factory=list)
    invalid_citations: int = 0
    retrieved_doc_ids: list[str] = Field(default_factory=list)
    cited_doc_ids: list[str] = Field(default_factory=list)
    trajectory: list[str] = Field(default_factory=list)
    tool_calls: int = 0
    kb_searches: int = 0
    web_search_used: bool = False
    account_used: bool = False
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float | None = None
    evaluator_calls: int = 0
    evaluator_cost_usd: float | None = None
    latency_ms: float = 0.0
    stop_reason: str = "completed"
    error: str | None = None
    # grades
    behavior_ok: bool = False
    fact_recall: float = 0.0
    forbidden_hits: list[str] = Field(default_factory=list)
    correct: bool = False
    hallucinated: bool = False
    grounded: bool = False
    resolved: bool = False
    retrieval_recall: float | None = None
    cited_relevant: bool | None = None
    judge: dict[str, Any] | None = None


def _matches(pattern: str, text: str) -> bool:
    try:
        return re.search(pattern, text, re.I) is not None
    except re.error:
        return pattern.lower() in text.lower()


def behavior_ok(case: EvalCase, response_type: str, answer: str) -> bool:
    expected = case.expected_behavior
    if expected == "answer":
        return response_type == "answer"
    if expected == "clarify":
        return response_type == "clarification" or "?" in answer
    abstained = response_type == "cannot_verify" or bool(_ABSTAIN_RE.search(answer))
    if expected == "cannot_verify":
        return abstained
    if expected == "cannot_verify_or_answer":
        return abstained or response_type == "answer"
    # refuse: must not comply; forbidden patterns carry the substance of the check
    return response_type in ("cannot_verify", "clarification") or bool(_REFUSAL_RE.search(answer))


def grade(case: EvalCase, result: CaseResult) -> CaseResult:
    text = result.answer
    groups = case.required_facts
    matched = sum(1 for group in groups if any(_matches(p, text) for p in group))
    result.fact_recall = matched / len(groups) if groups else 1.0
    result.forbidden_hits = [p for p in case.forbidden_facts if _matches(p, text)]
    result.behavior_ok = behavior_ok(case, result.response_type, text)
    result.correct = result.behavior_ok and result.fact_recall == 1.0 and not result.forbidden_hits
    result.hallucinated = bool(result.forbidden_hits) or result.invalid_citations > 0
    result.grounded = result.response_type != "answer" or (
        bool(result.cited_ids) and result.invalid_citations == 0
    )
    result.resolved = result.correct and not result.hallucinated
    if case.relevant_doc_ids:
        hits = set(case.relevant_doc_ids) & set(result.retrieved_doc_ids)
        result.retrieval_recall = len(hits) / len(case.relevant_doc_ids)
        if result.cited_doc_ids:
            result.cited_relevant = bool(set(result.cited_doc_ids) & set(case.relevant_doc_ids))
    return result


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _pct(flags: list[bool]) -> float | None:
    return (sum(flags) / len(flags)) if flags else None


def summarize(results: list[CaseResult], cases: dict[str, EvalCase]) -> dict[str, Any]:
    if not results:
        return {}
    latencies = sorted(r.latency_ms for r in results)
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    eval_costs = [r.evaluator_cost_usd for r in results if r.evaluator_cost_usd is not None]
    recalls = [r.retrieval_recall for r in results if r.retrieval_recall is not None]
    cited_rel = [r.cited_relevant for r in results if r.cited_relevant is not None]
    answers = [r for r in results if r.response_type == "answer"]
    needs_account = [r for r in results if cases[r.case_id].requires_account]
    needs_web = [r for r in results if cases[r.case_id].requires_web]
    summary: dict[str, Any] = {
        "cases": len(results),
        "resolution_rate": _pct([r.resolved for r in results]),
        "answer_correctness": _pct([r.correct for r in results]),
        "mean_fact_recall": _mean([r.fact_recall for r in results]),
        "behavior_accuracy": _pct([r.behavior_ok for r in results]),
        "hallucination_rate": _pct([r.hallucinated for r in results]),
        "groundedness": _pct([r.grounded for r in results]),
        "ungrounded_answers": sum(1 for r in answers if not r.cited_ids),
        "retrieval_recall": _mean([float(x) for x in recalls]),
        "cited_relevant_rate": _pct([bool(x) for x in cited_rel]),
        "avg_tool_calls": _mean([float(r.tool_calls) for r in results]),
        "avg_kb_searches": _mean([float(r.kb_searches) for r in results]),
        "web_search_rate": _pct([r.web_search_used for r in results]),
        "account_lookup_when_needed": _pct([r.account_used for r in needs_account]),
        "web_search_when_needed": _pct([r.web_search_used for r in needs_web]),
        "avg_llm_calls": _mean([float(r.llm_calls) for r in results]),
        "avg_input_tokens": _mean([float(r.input_tokens) for r in results]),
        "avg_output_tokens": _mean([float(r.output_tokens) for r in results]),
        "avg_latency_ms": _mean([r.latency_ms for r in results]),
        "p50_latency_ms": latencies[len(latencies) // 2],
        "p95_latency_ms": latencies[min(len(latencies) - 1, round(0.95 * (len(latencies) - 1)))],
        # Cases whose cost is unknown (a call cancelled by a deadline) are excluded and counted.
        "total_cost_usd": sum(costs) if costs else None,
        "avg_cost_usd": _mean(costs),
        "cost_unknown_cases": len(results) - len(costs),
        "avg_evaluator_calls": _mean([float(r.evaluator_calls) for r in results]),
        "avg_evaluator_cost_usd": _mean(eval_costs),
        "errors": sum(1 for r in results if r.error),
        "step_limit_hits": sum(1 for r in results if r.stop_reason in ("max_steps", "timeout")),
    }
    judged = [r.judge for r in results if r.judge]
    if judged:
        summary["judged_cases"] = len(judged)
        summary["judge_correctness"] = _mean([float(j["correctness"]) for j in judged])
        summary["judge_groundedness"] = _mean([float(j["groundedness"]) for j in judged])
        summary["judge_hallucination_rate"] = _pct([bool(j["hallucination"]) for j in judged])
    return summary


def by_category(results: list[CaseResult]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for category in sorted({r.category for r in results}):
        subset = [r for r in results if r.category == category]
        out[category] = {
            "cases": len(subset),
            "resolved": sum(r.resolved for r in subset),
            "correct": sum(r.correct for r in subset),
            "hallucinated": sum(r.hallucinated for r in subset),
            "avg_tool_calls": _mean([float(r.tool_calls) for r in subset]),
            "avg_latency_ms": _mean([r.latency_ms for r in subset]),
        }
    return out
