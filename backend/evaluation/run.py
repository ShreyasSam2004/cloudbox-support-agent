"""Benchmark CLI.

    uv run python -m backend.evaluation.run --out reports/<name> [--systems baseline,agent] [--judge] [--regrade]
                                            [--ids acct-01,acct-02] [--categories customer_specific]

Uses the models configured in the environment (.env). The dataset assumes "today" is 2026-10-09,
web search uses the hermetic fixture corpus, and customer data comes from the seed file, so runs are
reproducible. Results are appended per case; re-running with the same --out resumes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from backend.config.settings import Settings
from backend.container import Container
from backend.evaluation.baseline import BaselineRAG
from backend.evaluation.dataset import EvalCase, load_dataset
from backend.evaluation.judge import Judge
from backend.evaluation.metrics import by_category, summarize
from backend.evaluation.report import render_report
from backend.evaluation.runner import BenchmarkRunner, regrade_file, write_json
from backend.models.factory import build_llm
from backend.models.metered import MeteredLLM
from backend.observability.logging import configure_logging, get_logger
from backend.retrieval.ingestion import IngestionPipeline

log = get_logger(__name__)
DATASET_DATE = date(2026, 10, 9)


async def _main(args: argparse.Namespace) -> int:
    settings = Settings(
        agent_current_date=DATASET_DATE,
        web_search_provider="fixture",
        customer_store="json",
        session_store="memory",
        trace_store="memory",
    )
    configure_logging(settings.log_level, settings.log_json)
    cases = load_dataset(
        args.dataset,
        ids=args.ids.split(",") if args.ids else None,
        categories=args.categories.split(",") if args.categories else None,
    )
    if not cases:
        print("no cases selected")
        return 2
    if args.regrade:
        return _regrade(args.out, cases)
    container = await Container.create(settings)
    try:
        if await container.store.chunk_count() == 0:
            log.info("eval.index_empty_ingesting")
            await IngestionPipeline(
                container.store, container.embedder, max_chars=settings.chunk_max_chars
            ).ingest_directory(settings.data_dir / "knowledge_base")
        baseline = BaselineRAG(
            container.llm,
            container.retriever,
            top_k=settings.retrieval_top_k,
            chunk_chars=settings.observation_chunk_chars,
            max_output_tokens=settings.agent_max_output_tokens,
            effort=settings.agent_effort,
        )
        judge = Judge(MeteredLLM(build_llm(settings, "judge"))) if args.judge else None
        runner = BenchmarkRunner(container, baseline, judge, concurrency=args.concurrency)
        out: Path = args.out
        systems = [s.strip() for s in args.systems.split(",") if s.strip()]
        results = {s: await runner.run_system(s, cases, out) for s in systems}
        case_map = {c.id: c for c in cases}
        summaries = {s: summarize(r, case_map) for s, r in results.items()}
        categories = {s: by_category(r) for s, r in results.items()}
        run_info: dict[str, Any] = {
            "dataset": f"{args.dataset.as_posix()} ({len(cases)} cases)",
            "agent / baseline model": f"{container.llm.name}:{container.llm.model}",
            "retrieval evaluator model": (
                f"{container.evaluator_llm.name}:{container.evaluator_llm.model}"
                if container.evaluator_llm
                else "disabled"
            ),
            "embeddings": f"{settings.embedding_provider}:{settings.embedding_model}",
            "retrieval": (
                f"{settings.retrieval_mode}, top_k={settings.retrieval_top_k}, "
                f"re-rank pool={settings.retrieval_rerank_pool if settings.retrieval_evaluator_enabled else 0}, "
                f"chunk_max_chars={settings.chunk_max_chars}, store={settings.vector_store}"
            ),
            "agent limits": f"max_steps={settings.max_agent_steps}, max_tool_calls={settings.max_tool_calls}",
            "web search": "hermetic fixture corpus (data/web_fixtures)",
            "judge": f"{settings.judge_provider or settings.llm_provider}:{settings.judge_model or settings.agent_model}"
            if args.judge
            else "not run",
            "simulated date": DATASET_DATE.isoformat(),
            "finished": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        write_json(out / "summary.json", {"run": run_info, "summary": summaries, "by_category": categories})
        report = render_report(summaries=summaries, categories=categories, results=results, run_info=run_info)
        (out / "report.md").write_text(report, encoding="utf-8")
        print(json.dumps(summaries, indent=2, default=str))
        print(f"\nreport: {(out / 'report.md').as_posix()}")
    finally:
        await container.aclose()
    return 0


def _regrade(out: Path, cases: list[EvalCase]) -> int:
    """Re-grade stored answers with the current dataset (no model calls) and rewrite summary + report."""
    results = {
        system: regrade_file(out / f"{system}.jsonl", cases)
        for system in ("baseline", "agent")
        if (out / f"{system}.jsonl").exists()
    }
    if not results:
        print(f"no results in {out}")
        return 2
    case_map = {c.id: c for c in cases}
    summaries = {s: summarize(r, case_map) for s, r in results.items()}
    categories = {s: by_category(r) for s, r in results.items()}
    previous = out / "summary.json"
    run_info: dict[str, Any] = json.loads(previous.read_text("utf-8"))["run"] if previous.exists() else {}
    run_info["regraded"] = datetime.now(UTC).isoformat(timespec="seconds")
    write_json(out / "summary.json", {"run": run_info, "summary": summaries, "by_category": categories})
    report = render_report(summaries=summaries, categories=categories, results=results, run_info=run_info)
    (out / "report.md").write_text(report, encoding="utf-8")
    print(f"regraded {', '.join(results)}: {(out / 'report.md').as_posix()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cloudbox eval")
    parser.add_argument("--dataset", type=Path, default=Path("data/eval/cloudbox_support_v1.jsonl"))
    parser.add_argument(
        "--out", type=Path, default=Path("reports") / datetime.now(UTC).strftime("run-%Y%m%d-%H%M")
    )
    parser.add_argument("--systems", default="baseline,agent")
    parser.add_argument("--ids", default=None)
    parser.add_argument("--categories", default=None)
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument(
        "--regrade", action="store_true", help="Re-grade the stored answers in --out (no model calls)."
    )
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
