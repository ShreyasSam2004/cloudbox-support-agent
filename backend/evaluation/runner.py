"""Runs the baseline and the agent over the same cases and grades them.

Results are appended to ``<out>/<system>.jsonl`` as each case finishes, so a long run can be
interrupted and resumed without re-spending model calls.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path

from backend.agent.loop import AgentResult
from backend.container import Container
from backend.evaluation.baseline import BaselineRAG
from backend.evaluation.dataset import EvalCase
from backend.evaluation.judge import Judge
from backend.evaluation.metrics import CaseResult, grade
from backend.observability.logging import get_logger
from backend.schemas.domain import Evidence, SourceOrigin
from backend.security.auth import Principal
from backend.storage.sessions import Session

log = get_logger(__name__)
_TYPE_LINE = re.compile(r"^\s*TYPE:\s*\w+\s*\n", re.I)


def _session_for(case: EvalCase) -> Session:
    session = Session(session_id=uuid.uuid4().hex, owner="eval", bound_customer_id=case.customer_id)
    for turn in case.history:
        if turn.role == "user":
            session.add_user_turn(turn.content)
        else:
            session.add_assistant_turn(_TYPE_LINE.sub("", turn.content), "clarification", [])
    session.add_user_turn(case.question)
    return session


def _from_agent(case: EvalCase, result: AgentResult) -> CaseResult:
    trace = result.trace
    kb_docs = [e.doc_id for e in result.retrieved if e.origin == SourceOrigin.INTERNAL_KB and e.doc_id]
    cited_docs = [s.doc_id for s in result.sources if s.origin == SourceOrigin.INTERNAL_KB and s.doc_id]
    evaluator = [c for c in trace.llm_calls if c.purpose == "evaluator"]
    evaluator_costs = [c.cost_usd for c in evaluator]
    return CaseResult(
        case_id=case.id,
        category=case.category,
        system="agent",
        response_type=result.response_type,
        answer=result.answer,
        cited_ids=[s.evidence_id for s in result.sources],
        invalid_citations=int(result.evidence_summary.get("invalid_citations_removed", 0)),
        retrieved_doc_ids=list(dict.fromkeys(kb_docs)),
        cited_doc_ids=list(dict.fromkeys(cited_docs)),
        trajectory=trace.trajectory(),
        tool_calls=len(trace.tool_calls),
        kb_searches=sum(1 for c in trace.tool_calls if c.tool == "search_knowledge_base"),
        web_search_used=any(c.tool == "web_search" for c in trace.tool_calls),
        account_used=any(c.tool == "get_customer_account" and c.status == "ok" for c in trace.tool_calls),
        llm_calls=len(trace.llm_calls),
        input_tokens=result.usage.total_input_tokens,
        output_tokens=result.usage.output_tokens,
        cache_read_tokens=result.usage.cache_read_tokens,
        cost_usd=result.cost_usd,
        evaluator_calls=len(evaluator),
        evaluator_cost_usd=sum(c for c in evaluator_costs if c is not None)
        if all(c is not None for c in evaluator_costs)
        else None,
        latency_ms=result.latency_ms,
        stop_reason=result.stop_reason,
    )


def _judge_evidence(cited: list[Evidence]) -> list[str]:
    """The full text the system saw for each cited source (both systems are judged the same way)."""
    return [f"[{e.evidence_id}] {e.title}: {e.content or e.snippet}" for e in cited]


class BenchmarkRunner:
    def __init__(
        self, container: Container, baseline: BaselineRAG, judge: Judge | None = None, concurrency: int = 1
    ) -> None:
        self.container = container
        self.baseline = baseline
        self.judge = judge
        self.semaphore = asyncio.Semaphore(concurrency)

    async def _run_agent(self, case: EvalCase) -> CaseResult:
        session = _session_for(case)
        principal = Principal(subject="eval", customer_id=case.customer_id, authenticated=False)
        result = await self.container.agent.run(
            session=session, principal=principal, user_message=case.question
        )
        graded = grade(case, _from_agent(case, result))
        if self.judge:
            graded.judge = await self.judge.grade(case, result.answer, _judge_evidence(result.sources))
        return graded

    async def _run_baseline(self, case: EvalCase) -> CaseResult:
        result = await self.baseline.answer(case.question, execution_id=f"base_{case.id}", session_id="eval")
        trace = result.trace
        usage_in = sum(c.input_tokens + c.cache_read_tokens + c.cache_write_tokens for c in trace.llm_calls)
        costs = [c.cost_usd for c in trace.llm_calls]
        graded = grade(
            case,
            CaseResult(
                case_id=case.id,
                category=case.category,
                system="baseline",
                response_type=result.validated.response_type,
                answer=result.validated.text,
                cited_ids=result.validated.cited_ids,
                invalid_citations=len(result.validated.invalid_citations),
                retrieved_doc_ids=result.retrieved_doc_ids,
                cited_doc_ids=result.cited_doc_ids,
                trajectory=["retrieve", "generate"],
                llm_calls=len(trace.llm_calls),
                input_tokens=usage_in,
                output_tokens=sum(c.output_tokens for c in trace.llm_calls),
                cache_read_tokens=sum(c.cache_read_tokens for c in trace.llm_calls),
                cost_usd=sum(c for c in costs if c is not None)
                if all(c is not None for c in costs)
                else None,
                evaluator_cost_usd=0.0,
                latency_ms=result.latency_ms,
                error=result.error,
            ),
        )
        if self.judge:
            graded.judge = await self.judge.grade(case, result.validated.text, _judge_evidence(result.cited))
        return graded

    async def run_system(self, system: str, cases: list[EvalCase], out_dir: Path) -> list[CaseResult]:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{system}.jsonl"
        done = load_results(path)
        pending = [c for c in cases if c.id not in done]
        log.info("eval.system_started", system=system, pending=len(pending), resumed=len(done))
        lock = asyncio.Lock()

        async def run_one(case: EvalCase) -> None:
            async with self.semaphore:
                try:
                    result = await (self._run_agent(case) if system == "agent" else self._run_baseline(case))
                except Exception as exc:  # a crash in one case must not lose the run
                    log.exception("eval.case_failed", case=case.id, system=system)
                    result = grade(
                        case,
                        CaseResult(
                            case_id=case.id,
                            category=case.category,
                            system=system,
                            response_type="cannot_verify",
                            answer="",
                            error=repr(exc)[:300],
                        ),
                    )
            async with lock:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(result.model_dump_json() + "\n")
                done[case.id] = result
                log.info(
                    "eval.case_done",
                    system=system,
                    case=case.id,
                    resolved=result.resolved,
                    latency_s=round(result.latency_ms / 1000, 1),
                    trajectory=result.trajectory,
                )

        await asyncio.gather(*(run_one(c) for c in pending))
        order = {c.id: i for i, c in enumerate(cases)}
        return sorted((r for r in done.values() if r.case_id in order), key=lambda r: order[r.case_id])


def load_results(path: Path) -> dict[str, CaseResult]:
    done: dict[str, CaseResult] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = CaseResult.model_validate_json(line)
                done[item.case_id] = item
    return done


def regrade_file(path: Path, cases: list[EvalCase]) -> list[CaseResult]:
    """Re-apply the deterministic grading to stored answers (no model calls; judge scores are kept)."""
    stored = load_results(path)
    results = [grade(case, stored[case.id]) for case in cases if case.id in stored]
    path.write_text("".join(r.model_dump_json() + "\n" for r in results), encoding="utf-8")
    return results


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
