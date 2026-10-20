from __future__ import annotations

from backend.models.base import LLMError, LLMResponse
from backend.models.scripted import ScriptedProvider, text_response
from backend.retrieval.evaluator import RetrievalEvaluator, _parse_verdict

PASSAGES = [
    ("K1", "Refund Policy", "3.2 Charges after cancellation", "Full refund if cancelled before renewal.")
]


def test_parse_verdict_tolerates_fences_and_scales() -> None:
    verdict = _parse_verdict(
        '```json\n{"relevant": true, "confidence": 85, "coverage": "partial", '
        '"useful_evidence_ids": ["K1"], "missing_information": "account dates", "reason": "ok"}\n```'
    )
    assert verdict.relevant is True
    assert verdict.confidence == 0.85
    assert verdict.coverage == "partial"


def test_parse_verdict_passage_scores() -> None:
    verdict = _parse_verdict(
        '{"passage_scores": [{"id": "CAND-1", "score": 3}, {"id": "cand-2", "score": 7}, '
        '{"id": "cand-3", "score": -1}, {"id": "cand-9", "score": 3}, {"id": "cand-4", "score": "x"}], '
        '"relevant": true, "confidence": 0.9, "coverage": "full", "missing_information": "", "reason": "ok"}',
        ["cand-1", "cand-2", "cand-3", "cand-4"],
    )
    assert verdict.passage_scores == {"cand-1": 3, "cand-2": 3, "cand-3": 0}  # clamped; unknown ignored
    assert verdict.useful_evidence_ids == ["cand-1", "cand-2"]


async def test_evaluator_receives_question_query_and_passages() -> None:
    llm = ScriptedProvider(
        [
            text_response(
                '{"relevant": false, "confidence": 0.3, "coverage": "none", "useful_evidence_ids": [], '
                '"missing_information": "refund eligibility rules", "reason": "generic"}'
            )
        ]
    )
    verdict = await RetrievalEvaluator(llm).evaluate("Can I get a refund?", "subscription", PASSAGES)
    assert verdict.relevant is False
    assert verdict.missing_information == "refund eligibility rules"
    request = llm.requests[0]
    assert request.purpose == "evaluator"
    assert request.response_schema is not None
    prompt = request.messages[0].text
    assert "Can I get a refund?" in prompt and "<search_query>subscription</search_query>" in prompt
    assert 'id="K1"' in prompt


async def test_evaluator_failure_degrades_gracefully() -> None:
    llm = ScriptedProvider([LLMError("boom", retryable=True, provider="scripted")])
    verdict = await RetrievalEvaluator(llm).evaluate("q", "q", PASSAGES)
    assert verdict.relevant is None and verdict.evaluator_status == "error"

    garbage = ScriptedProvider([text_response("not json at all")])
    verdict = await RetrievalEvaluator(garbage).evaluate("q", "q", PASSAGES)
    assert verdict.evaluator_status == "error"


async def test_no_passages_short_circuits_without_model_call() -> None:
    llm = ScriptedProvider([])
    verdict = await RetrievalEvaluator(llm).evaluate("q", "q", [])
    assert verdict.relevant is False and verdict.coverage == "none"
    assert llm.requests == []


async def test_disabled_evaluator() -> None:
    verdict = await RetrievalEvaluator(None, enabled=True).evaluate("q", "q", PASSAGES)
    assert verdict.evaluator_status == "disabled"
    _ = LLMResponse  # imported for type completeness
