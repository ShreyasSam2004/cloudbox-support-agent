"""Evaluation harness tests: dataset integrity, grading rules and an end-to-end scripted run."""

from __future__ import annotations

import json
import re

from backend.evaluation.baseline import BaselineRAG
from backend.evaluation.dataset import EvalCase, load_dataset
from backend.evaluation.metrics import CaseResult, grade, summarize
from backend.evaluation.report import render_report
from backend.evaluation.runner import BenchmarkRunner
from backend.models.base import LLMRequest, LLMResponse
from backend.models.scripted import text_response, tool_response
from tests.conftest import DATA, build_container

DATASET = DATA / "eval" / "cloudbox_support_v1.jsonl"


def test_dataset_is_consistent_with_corpus_and_customers() -> None:
    cases = load_dataset(DATASET)
    assert len(cases) >= 40
    assert len({c.id for c in cases}) == len(cases)
    doc_ids = {p.stem for p in (DATA / "knowledge_base").glob("*.md")}
    customers = {
        c["customer_id"] for c in json.loads((DATA / "customers" / "customers.json").read_text("utf-8"))
    }
    for case in cases:
        assert set(case.relevant_doc_ids) <= doc_ids, case.id
        if case.customer_id:
            assert case.customer_id in customers, case.id
        for group in case.required_facts:
            for pattern in group:
                re.compile(pattern)
        for pattern in case.forbidden_facts:
            re.compile(pattern)
    categories = {c.category for c in cases}
    assert {
        "straightforward_faq",
        "multi_document",
        "policy_exception",
        "customer_specific",
        "ambiguous",
        "requires_web",
        "kb_missing",
        "adversarial",
        "conversation_memory",
    } <= categories


def _case(**kw: object) -> EvalCase:
    base: dict[str, object] = {"id": "x", "category": "c", "question": "q", "expected_behavior": "answer"}
    base.update(kw)
    return EvalCase.model_validate(base)


def _result(**kw: object) -> CaseResult:
    base: dict[str, object] = {
        "case_id": "x",
        "category": "c",
        "system": "agent",
        "response_type": "answer",
        "answer": "",
        "cited_ids": ["K1"],
    }
    base.update(kw)
    return CaseResult.model_validate(base)


def test_grading_rules() -> None:
    case = _case(
        required_facts=[["24 hours", "24-hour"], ["rotate"]],
        forbidden_facts=["never expires"],
        relevant_doc_ids=["api-authentication"],
    )
    good = grade(
        case,
        _result(
            answer="Rotate it; the old key works for 24 hours [K1].",
            retrieved_doc_ids=["api-authentication"],
            cited_doc_ids=["api-authentication"],
        ),
    )
    assert good.correct and good.resolved and good.grounded
    assert good.retrieval_recall == 1.0 and good.cited_relevant is True

    partial = grade(case, _result(answer="Rotate it [K1]."))
    assert partial.fact_recall == 0.5 and not partial.correct

    lie = grade(case, _result(answer="Rotate it; it never expires, 24 hours [K1]."))
    assert lie.hallucinated and not lie.resolved

    fabricated = grade(case, _result(answer="Rotate, 24 hours [K1].", invalid_citations=1))
    assert fabricated.hallucinated

    uncited = grade(case, _result(answer="Rotate, 24 hours.", cited_ids=[]))
    assert uncited.correct and not uncited.grounded


def _hallucinated(case_id: str, response_type: str, answer: str) -> bool:
    case = next(c for c in load_dataset(DATASET) if c.id == case_id)
    result = CaseResult(
        case_id=case_id, category=case.category, system="t", response_type=response_type, answer=answer
    )
    return grade(case, result).hallucinated


def test_forbidden_patterns_match_claims_not_negations() -> None:
    """Regression: correct answers that *mention* a wrong fact in order to deny it are not hallucinations."""
    claims = [
        ("exc-01", "answer", "Paid plans come with a 30-day money-back guarantee."),
        ("acct-03", "answer", "This is most likely an authorization hold, not a real charge."),
        ("nokb-02", "answer", "Yes, CloudBox has a native Salesforce integration."),
        ("adv-01", "answer", "Yes, CloudBox offers a 60-day money-back guarantee on every plan."),
    ]
    negations = [
        ("exc-01", "answer", "Note that the old 30-day money-back guarantee was retired on 2025-12-31."),
        (
            "acct-03",
            "answer",
            "These are two settled charges, not a pending bank hold. A pending hold isn't a charge.",
        ),
        ("nokb-02", "cannot_verify", "I can't verify whether CloudBox has a native Salesforce integration."),
        (
            "nokb-02",
            "cannot_verify",
            "Nothing in the docs says CloudBox has a native Salesforce integration.",
        ),
        ("adv-01", "answer", "I can't confirm that. CloudBox doesn't offer a 60-day money-back guarantee."),
    ]
    assert all(_hallucinated(*c) for c in claims)
    assert not any(_hallucinated(*n) for n in negations)


def test_behavior_rules() -> None:
    clarify = _case(expected_behavior="clarify")
    assert grade(clarify, _result(response_type="clarification", answer="Which plan?")).behavior_ok
    abstain = _case(expected_behavior="cannot_verify")
    assert grade(
        abstain, _result(response_type="answer", answer="Our documentation doesn't mention HIPAA.")
    ).behavior_ok
    assert not grade(abstain, _result(response_type="answer", answer="Yes, we sign BAAs.")).behavior_ok
    refuse = _case(expected_behavior="refuse", forbidden_facts=["globex"])
    assert grade(
        refuse, _result(response_type="answer", answer="I can only discuss your own account.")
    ).resolved
    assert not grade(refuse, _result(response_type="answer", answer="Globex is on Enterprise.")).resolved


async def test_end_to_end_scripted_benchmark(kb_store, tmp_path) -> None:  # type: ignore[no-untyped-def]
    def agent(request: LLMRequest) -> LLMResponse:
        if request.purpose == "baseline":
            return text_response("TYPE: answer\nRotate the key [K1].")
        results = [b for m in request.messages for b in m.content if getattr(b, "type", "") == "tool_result"]
        if not results:
            return tool_response(("search_knowledge_base", {"query": "rotate API key grace period"}))
        return text_response(
            "TYPE: answer\nRotate it in Settings > Developer > API keys; the old one works for 24 hours [K1]."
        )

    container, _, _ = await build_container(kb_store, agent)
    cases = [c for c in load_dataset(DATASET) if c.id in ("faq-01", "amb-02")]
    baseline = BaselineRAG(container.llm, container.retriever, top_k=4)
    runner = BenchmarkRunner(container, baseline)
    results = {s: await runner.run_system(s, cases, tmp_path) for s in ("baseline", "agent")}
    assert (tmp_path / "agent.jsonl").exists()
    by_id = {r.case_id: r for r in results["agent"]}
    assert by_id["faq-01"].resolved
    assert by_id["faq-01"].trajectory == ["search_knowledge_base", "answer"]
    assert not results["baseline"][0].resolved  # baseline answer lacks the 24-hour fact

    # Resuming does not re-run finished cases.
    again = await runner.run_system("agent", cases, tmp_path)
    assert len(again) == 2
    assert len((tmp_path / "agent.jsonl").read_text().splitlines()) == 2

    case_map = {c.id: c for c in cases}
    summaries = {s: summarize(r, case_map) for s, r in results.items()}
    report = render_report(
        summaries=summaries,
        categories={s: {} for s in results},
        results=results,
        run_info={"model": "scripted"},
    )
    assert "Successful resolution rate" in report and "Agent trajectories" in report
