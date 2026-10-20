"""Optional LLM-as-judge (secondary signal; deterministic grading is primary)."""

from __future__ import annotations

import json
from typing import Any

from backend.evaluation.dataset import EvalCase
from backend.models.base import ChatMessage, LLMError, LLMProvider, LLMRequest
from backend.observability.logging import get_logger

log = get_logger(__name__)

JUDGE_SYSTEM = """You grade answers from a customer-support assistant for CloudBox (a fictional SaaS company).
You get the customer question, a reference answer written by CloudBox staff, the assistant's answer, and the
evidence passages the assistant cited. Score strictly:
- correctness (1-5): does the answer give the customer the right outcome and key facts of the reference? Extra
  correct detail is fine; a wrong eligibility decision, amount, deadline or policy is at most 2.
- groundedness (1-5): are the answer's CloudBox-specific claims supported by the cited evidence?
- hallucination (true/false): does the answer state any CloudBox policy, number, deadline or account fact that is
  neither in the evidence nor in the reference answer?
Return only JSON."""

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        # No minimum/maximum: structured-output modes reject numeric constraints; scores are clamped below.
        "correctness": {"type": "integer"},
        "groundedness": {"type": "integer"},
        "hallucination": {"type": "boolean"},
        "rationale": {"type": "string"},
    },
    "required": ["correctness", "groundedness", "hallucination", "rationale"],
    "additionalProperties": False,
}


class Judge:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def grade(self, case: EvalCase, answer: str, evidence: list[str]) -> dict[str, Any] | None:
        prompt = (
            f"<question>{case.question}</question>\n<reference_answer>{case.reference_answer}</reference_answer>\n"
            f"<assistant_answer>{answer}</assistant_answer>\n<cited_evidence>\n"
            + "\n---\n".join(evidence[:8])
            + "\n</cited_evidence>"
        )
        try:
            response = await self.llm.complete(
                LLMRequest(
                    system=JUDGE_SYSTEM,
                    messages=[ChatMessage.user(prompt)],
                    response_schema=JUDGE_SCHEMA,
                    max_output_tokens=2048,
                    effort="low",
                    purpose="judge",
                )
            )
            text = response.text
            data: dict[str, Any] = json.loads(text[text.find("{") : text.rfind("}") + 1])
        except (LLMError, ValueError) as exc:
            log.warning("judge.failed", case=case.id, error=type(exc).__name__, detail=str(exc)[:200])
            return None
        return {
            "correctness": min(max(int(data.get("correctness", 1)), 1), 5),
            "groundedness": min(max(int(data.get("groundedness", 1)), 1), 5),
            "hallucination": bool(data.get("hallucination", False)),
            "rationale": str(data.get("rationale", ""))[:400],
        }
