"""Markdown report generation."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from backend.evaluation.metrics import CaseResult

_ROWS: list[tuple[str, str, str]] = [
    # key, label, format
    ("resolution_rate", "Successful resolution rate", "pct"),
    ("answer_correctness", "Answer correctness (strict)", "pct"),
    ("mean_fact_recall", "Mean required-fact recall", "pct"),
    ("behavior_accuracy", "Expected behaviour (answer / clarify / abstain / refuse)", "pct"),
    ("hallucination_rate", "Hallucination rate (lower is better)", "pct"),
    ("groundedness", "Groundedness (answers with valid citations)", "pct"),
    ("ungrounded_answers", "Answers without any citation (count)", "int"),
    ("retrieval_recall", "Retrieval recall of relevant documents", "pct"),
    ("cited_relevant_rate", "Cited a relevant document (when citing KB)", "pct"),
    ("account_lookup_when_needed", "Account looked up when required", "pct"),
    ("web_search_when_needed", "Web searched when required", "pct"),
    ("web_search_rate", "Web-search frequency (all cases)", "pct"),
    ("avg_tool_calls", "Avg tool calls", "num"),
    ("avg_kb_searches", "Avg knowledge-base searches", "num"),
    ("avg_llm_calls", "Avg LLM calls (incl. evaluator)", "num"),
    ("avg_input_tokens", "Avg input tokens", "int"),
    ("avg_output_tokens", "Avg output tokens", "int"),
    ("avg_latency_ms", "Avg latency (s)", "sec"),
    ("p50_latency_ms", "p50 latency (s)", "sec"),
    ("p95_latency_ms", "p95 latency (s)", "sec"),
    ("avg_cost_usd", "Avg estimated cost per question (USD)", "usd"),
    ("avg_evaluator_calls", "Avg retrieval-evaluator calls", "num"),
    ("avg_evaluator_cost_usd", "Avg retrieval-evaluator cost per question (USD, incl. above)", "usd"),
    ("total_cost_usd", "Total estimated cost (USD)", "usd"),
    ("cost_unknown_cases", "Cases with unknown cost (excluded above)", "int"),
    ("step_limit_hits", "Step/time-limit hits", "int"),
    ("errors", "Errors", "int"),
    ("judged_cases", "LLM-judge: cases graded", "int"),
    ("judge_correctness", "LLM-judge correctness (1-5)", "num"),
    ("judge_groundedness", "LLM-judge groundedness (1-5)", "num"),
    ("judge_hallucination_rate", "LLM-judge hallucination rate", "pct"),
]


def _fmt(value: Any, kind: str) -> str:
    if value is None:
        return "n/a"
    if kind == "pct":
        return f"{100 * value:.1f}%"
    if kind == "int":
        return f"{round(value):,}"
    if kind == "sec":
        return f"{value / 1000:.1f}"
    if kind == "usd":
        return f"${value:.4f}"
    return f"{value:.2f}"


def _count(results: list[CaseResult], attr: str) -> str:
    return f"{sum(bool(getattr(r, attr)) for r in results)}/{len(results)}"


def render_report(
    *,
    summaries: dict[str, dict[str, Any]],
    categories: dict[str, dict[str, dict[str, Any]]],
    results: dict[str, list[CaseResult]],
    run_info: dict[str, Any],
) -> str:
    systems = [s for s in ("baseline", "agent") if s in summaries]
    lines: list[str] = []
    lines.append("# CloudBox Support Benchmark — Baseline RAG vs. Agentic RAG\n")
    lines.append(
        f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}. All numbers below were produced by "
        "running both systems on the same dataset; nothing is estimated except cost (token counts × list price).\n"
    )
    lines.append("## Run configuration\n")
    for key, value in run_info.items():
        lines.append(f"- **{key}**: {value}")
    lines.append("")

    lines.append("## Headline metrics\n")
    header = (
        "| Metric | "
        + " | ".join(s.title() for s in systems)
        + (" | Δ (agent − baseline) |" if len(systems) == 2 else " |")
    )
    lines.append(header)
    lines.append("|---" * (len(systems) + 1 + (1 if len(systems) == 2 else 0)) + "|")
    for key, label, kind in _ROWS:
        values = [summaries[s].get(key) for s in systems]
        if all(v is None for v in values) and key.startswith("judge"):
            continue
        row = f"| {label} | " + " | ".join(_fmt(v, kind) for v in values)
        if len(systems) == 2:
            a, b = values[0], values[1]
            if a is not None and b is not None and kind in ("pct", "num", "sec", "int", "usd"):
                delta = b - a
                if kind == "pct":
                    row += f" | {100 * delta:+.1f} pp"
                elif kind == "sec":
                    row += f" | {delta / 1000:+.1f}"
                elif kind == "usd":
                    row += f" | {delta:+.4f}"
                else:
                    row += f" | {delta:+.2f}"
            else:
                row += " | "
        lines.append(row + " |")
    lines.append("")
    for system in systems:
        rs = results[system]
        lines.append(
            f"Counts — **{system}**: resolved {_count(rs, 'resolved')}, correct {_count(rs, 'correct')}, "
            f"hallucinated {_count(rs, 'hallucinated')}."
        )
    lines.append("")

    lines.append("## By category (resolved / cases)\n")
    cats = sorted({c for s in systems for c in categories[s]})
    lines.append("| Category | " + " | ".join(s.title() for s in systems) + " |")
    lines.append("|---" * (len(systems) + 1) + "|")
    for cat in cats:
        cells = []
        for s in systems:
            c = categories[s].get(cat)
            cells.append(f"{c['resolved']}/{c['cases']}" if c else "n/a")
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")
    lines.append("")

    if "agent" in results:
        lines.append("## Agent trajectories\n")
        lines.append("Distinct action sequences chosen by the model (the code does not prescribe them):\n")
        counter = Counter(" → ".join(r.trajectory) for r in results["agent"])
        lines.append("| Trajectory | Cases |")
        lines.append("|---|---|")
        for traj, n in counter.most_common():
            lines.append(f"| {traj or '(none)'} | {n} |")
        lines.append("")

    lines.append("## Per-case results\n")
    lines.append("| Case | Category | " + " | ".join(f"{s.title()}" for s in systems) + " |")
    lines.append("|---|---|" + "---|" * len(systems))
    by_id = {s: {r.case_id: r for r in results[s]} for s in systems}
    for case_id in [r.case_id for r in results[systems[0]]]:
        cells = []
        for s in systems:
            r = by_id[s].get(case_id)
            if r is None:
                cells.append("n/a")
                continue
            status = "✅" if r.resolved else ("⚠️ halluc." if r.hallucinated else "❌")
            cells.append(f"{status} {r.response_type}, facts {r.fact_recall:.0%}, {r.latency_ms / 1000:.1f}s")
        lines.append(f"| {case_id} | {by_id[systems[0]][case_id].category} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append(
        "Raw per-case outputs (answers, citations, trajectories, grades) are in the `*.jsonl` files next to this report."
    )
    return "\n".join(lines) + "\n"
