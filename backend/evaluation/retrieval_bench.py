"""Retrieval benchmark: chunking strategy, search mode, top-k and LLM re-ranking, measured on labelled evidence.

    uv run python -m backend.evaluation.retrieval_bench --out reports/retrieval \
        [--rerank claude-haiku-5-5:10,claude-sonnet-5-5:10] [--lexical-weight 0.5] [--top-k 6]

Ground truth: every answerable case in the dataset lists ``evidence`` — short verbatim phrases from the
knowledge base that a correct answer needs. A phrase counts as *found* when it appears (normalised)
inside a returned passage **as the agent sees it** (truncated to ``view_chars``). Because the labels are
text, not chunk IDs, any chunking strategy can be scored with the same labels.

The query is the customer's question verbatim. The agent usually searches with a rewritten query, so
these numbers are a conservative, model-free proxy for its first search.

Costs: embeddings only (cached in ``.data/``), plus one evaluator call per case for each ``--rerank``
spec. Uses the embedding and LLM providers configured in ``.env``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import statistics
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np

from backend.config.pricing import estimate_cost_usd
from backend.config.settings import Settings
from backend.evaluation.dataset import EvalCase, load_dataset
from backend.models.base import LLMProvider, LLMRequest, LLMResponse
from backend.models.factory import build_provider
from backend.retrieval.chunking import chunk_document
from backend.retrieval.embeddings import Embedder, build_embedder
from backend.retrieval.evaluator import RetrievalEvaluator
from backend.retrieval.ingestion import build_records
from backend.retrieval.parsing import parse_markdown, split_front_matter
from backend.retrieval.rerank import candidate_label, rerank
from backend.retrieval.retriever import Retriever
from backend.retrieval.vector_store import InMemoryVectorStore
from backend.schemas.domain import ChunkRecord, DocumentRecord

KS = (1, 2, 3, 4, 5, 6, 8, 10, 15, 20)
BUDGETS = (1500, 3000, 6000)  # characters of context handed to the model
DEPTH = 20  # ranking depth retrieved per query


@dataclass(frozen=True)
class SearchConfig:
    mode: Literal["vector", "lexical", "hybrid"]
    lexical_weight: float = 1.0

    @property
    def label(self) -> str:
        return f"hybrid (keyword weight {self.lexical_weight:g})" if self.mode == "hybrid" else self.mode


# --------------------------------------------------------------------------- evidence matching


def normalize(text: str) -> str:
    """Case/markup-insensitive form used for evidence matching (bold, code ticks, table pipes, dashes)."""
    text = unicodedata.normalize("NFKC", text).replace("–", "-").replace("—", "-")
    text = re.sub(r"\|", " ", re.sub(r"[*`]", "", text.lower()))
    return re.sub(r"\s+", " ", text).strip()


def found_phrases(phrases: list[str], passages: list[str]) -> set[int]:
    views = [normalize(p) for p in passages]
    return {i for i, phrase in enumerate(phrases) if any(normalize(phrase) in view for view in views)}


# --------------------------------------------------------------------------- chunking strategies


@dataclass(frozen=True)
class Strategy:
    name: str
    kind: Literal["structured", "fixed"]
    max_chars: int = 1600
    context_chars: int = 420  # structured: parent-intro context carried into child chunks (0 = off)
    overlap: int = 0  # fixed windows
    view_chars: int = 2000  # characters of each passage the agent sees
    note: str = ""


STRATEGIES = (
    Strategy("structured-1600", "structured", note="current chunker (default)"),
    Strategy("structured-800", "structured", max_chars=800),
    Strategy("structured-2400", "structured", max_chars=2400),
    Strategy("structured-1600-no-context", "structured", context_chars=0, note="no parent-intro context"),
    Strategy("structured-1600-view-1400", "structured", view_chars=1400, note="old 1,400-char passage cut"),
    Strategy("fixed-400", "fixed", max_chars=400, overlap=80, note="naive windows, 20% overlap"),
    Strategy("fixed-800", "fixed", max_chars=800, overlap=160, note="naive windows, 20% overlap"),
    Strategy("fixed-1600", "fixed", max_chars=1600, overlap=320, note="naive windows, 20% overlap"),
)


def _windows(body: str, size: int, overlap: int) -> list[str]:
    """Fixed-size character windows snapped to whitespace (the classic naive chunker)."""
    out: list[str] = []
    start = 0
    while start < len(body):
        end = min(len(body), start + size)
        if end < len(body):
            cut = body.rfind(" ", start + int(size * 0.8), end)
            end = cut if cut > start else end
        piece = body[start:end].strip()
        if piece:
            out.append(piece)
        if end >= len(body):
            break
        snap = body.find(" ", end - overlap)
        start = snap + 1 if 0 <= snap < end else end
    return out


def _record(document: DocumentRecord, i: int, section: str, content: str, embedding_text: str) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=f"{document.doc_id}::{i:03d}",
        doc_id=document.doc_id,
        title=document.title,
        section_path=section,
        content=content,
        embedding_text=embedding_text,
        ordinal=i,
        metadata=document.metadata,
    )


def chunk_corpus(
    strategy: Strategy, sources: list[tuple[str, str]]
) -> list[tuple[DocumentRecord, list[ChunkRecord]]]:
    corpus: list[tuple[DocumentRecord, list[ChunkRecord]]] = []
    for path, raw in sources:
        document, records = build_records(raw, path, "bench", max_chars=strategy.max_chars)
        if strategy.kind == "structured" and strategy.context_chars != Strategy.context_chars:
            drafts = chunk_document(
                parse_markdown(raw), max_chars=strategy.max_chars, context_max_chars=strategy.context_chars
            )
            records = [
                _record(document, i, " > ".join(d.section_path), d.content, d.embedding_text)
                for i, d in enumerate(drafts)
            ]
        elif strategy.kind == "fixed":
            _, body = split_front_matter(raw)
            windows = _windows(body, strategy.max_chars, strategy.overlap)
            records = [
                _record(document, i, document.title, w, f"{document.title}\n{w}")
                for i, w in enumerate(windows)
            ]
        corpus.append((document, records))
    return corpus


# --------------------------------------------------------------------------- embeddings cache


class CachedEmbedder:
    """Wraps an embedder with an on-disk cache keyed by (model, text) so repeated runs are free."""

    def __init__(self, inner: Embedder, path: Path) -> None:
        self.inner = inner
        self.model = inner.model
        self.dim = inner.dim
        self.path = path
        self.cache: dict[str, np.ndarray] = {}
        if path.exists():
            with np.load(path) as data:
                self.cache = {key: data[key] for key in data.files}
        self.misses = 0

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}\x00{self.dim}\x00{text}".encode()).hexdigest()

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        keys = [self._key(t) for t in texts]
        missing = list(dict.fromkeys(k for k in keys if k not in self.cache))
        if missing:
            by_key = dict(zip(keys, texts, strict=True))
            vectors = await self.inner.embed_documents([by_key[k] for k in missing])
            self.misses += len(missing)
            for key, vector in zip(missing, vectors, strict=True):
                self.cache[key] = np.asarray(vector, dtype=np.float32)
        return [self.cache[k].tolist() for k in keys]

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(self.path, **self.cache)  # type: ignore[arg-type]

    async def aclose(self) -> None:
        await self.inner.aclose()


async def build_store(
    strategy: Strategy, sources: list[tuple[str, str]], embedder: Embedder
) -> tuple[InMemoryVectorStore, list[ChunkRecord]]:
    store = InMemoryVectorStore(None)
    await store.ensure_index(embedder.model, embedder.dim)
    chunks: list[ChunkRecord] = []
    for document, records in chunk_corpus(strategy, sources):
        vectors = await embedder.embed_documents([r.embedding_text for r in records])
        await store.upsert_document(document, records, vectors)
        chunks.extend(records)
    return store, chunks


async def rank(
    store: InMemoryVectorStore, embedder: Embedder, config: SearchConfig, query: str, rrf_k: int
) -> list[ChunkRecord]:
    if config.mode == "lexical":
        return [c for c, _ in await store.lexical_search(query, DEPTH)]
    retriever = Retriever(
        store,
        embedder,
        mode=config.mode,
        candidate_k=DEPTH,
        rrf_k=rrf_k,
        lexical_weight=config.lexical_weight,
    )
    return [s.chunk for s in (await retriever.search(query, DEPTH)).chunks]


# --------------------------------------------------------------------------- scoring


def score_ranking(case: EvalCase, ranking: list[ChunkRecord], view_chars: int) -> dict[str, Any]:
    """Per-case metrics for one ranked list of passages."""
    phrases = case.evidence
    views = [c.content[:view_chars] for c in ranking]
    first_hit = next((i for i, v in enumerate(views, start=1) if found_phrases(phrases, [v])), None)
    per_k = {}
    for k in KS:
        found = found_phrases(phrases, views[:k])
        per_k[k] = {
            "found": len(found),
            "complete": len(found) == len(phrases),
            "chars": sum(map(len, views[:k])),
        }
    per_budget = {}
    for budget in BUDGETS:
        n, used = 0, 0
        while n < len(views) and (n == 0 or used + len(views[n]) <= budget):
            used += len(views[n])
            n += 1
        per_budget[budget] = len(found_phrases(phrases, views[:n]))
    return {"phrases": len(phrases), "first_hit": first_hit, "per_k": per_k, "per_budget": per_budget}


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(r["phrases"] for r in rows)
    out: dict[str, Any] = {
        "cases": len(rows),
        "phrases": total,
        "mrr": statistics.fmean(1 / r["first_hit"] if r["first_hit"] else 0.0 for r in rows),
    }
    for k in KS:
        out[f"recall@{k}"] = sum(r["per_k"][k]["found"] for r in rows) / total
        out[f"complete@{k}"] = sum(r["per_k"][k]["complete"] for r in rows) / len(rows)
        out[f"chars@{k}"] = statistics.fmean(r["per_k"][k]["chars"] for r in rows)
    for budget in BUDGETS:
        out[f"recall@{budget}chars"] = sum(r["per_budget"][budget] for r in rows) / total
    return out


# --------------------------------------------------------------------------- re-ranking experiment


class _UsageTap:
    """Records token usage, estimated cost and latency of every call made through it."""

    def __init__(self, inner: LLMProvider) -> None:
        self.inner = inner
        self.name = inner.name
        self.model = inner.model
        self.calls: list[dict[str, float]] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        response = await self.inner.complete(request)
        u = response.usage
        cost = estimate_cost_usd(
            self.name, self.model, u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens
        )
        self.calls.append(
            {
                "input_tokens": u.input_tokens + u.cache_read_tokens + u.cache_write_tokens,
                "output_tokens": u.output_tokens,
                "cost_usd": cost or 0.0,
                "latency_s": time.perf_counter() - started,
            }
        )
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


async def rerank_experiment(
    settings: Settings,
    spec: str,
    cases: list[EvalCase],
    candidates: dict[str, list[ChunkRecord]],
    view_chars: int,
) -> dict[str, Any]:
    model, _, pool_text = spec.partition(":")
    pool = int(pool_text or settings.retrieval_rerank_pool)
    tap = _UsageTap(build_provider(settings, settings.effective_evaluator_provider, model))
    evaluator = RetrievalEvaluator(tap, effort=settings.evaluator_effort, passage_chars=view_chars)
    semaphore = asyncio.Semaphore(4)

    async def judge(case: EvalCase) -> dict[str, Any]:
        pool_chunks = candidates[case.id][:pool]
        labels = [candidate_label(i) for i in range(1, len(pool_chunks) + 1)]
        passages = [
            (label, c.title, c.section_path, c.content[:view_chars])
            for label, c in zip(labels, pool_chunks, strict=True)
        ]
        async with semaphore:
            verdict = await evaluator.evaluate(case.question, case.question, passages)
        by_label = dict(zip(labels, pool_chunks, strict=True))
        in_pool = len(found_phrases(case.evidence, [p[3] for p in passages])) if case.evidence else 0
        return {
            "case": case,
            "ranking": [by_label[label] for label in rerank(labels, verdict.passage_scores, pool)],
            "truth": "none" if in_pool == 0 else ("full" if in_pool == len(case.evidence) else "partial"),
            "relevant": verdict.relevant,
            "coverage": verdict.coverage,
            "reason": verdict.reason,
            "status": verdict.evaluator_status,
        }

    try:
        judged = await asyncio.gather(*(judge(c) for c in cases))
    finally:
        await tap.aclose()
    rows = [score_ranking(j["case"], j["ranking"], view_chars) for j in judged if j["case"].evidence]
    full = [j for j in judged if j["truth"] == "full"]
    none = [j for j in judged if j["truth"] == "none"]
    calls = tap.calls or [{"cost_usd": 0.0, "input_tokens": 0.0, "output_tokens": 0.0, "latency_s": 0.0}]
    return {
        "spec": f"{model}, pool {pool}",
        "model": model,
        "pool": pool,
        "metrics": aggregate(rows),
        "verdict": {
            "full_cases": len(full),
            "relevant_when_full": sum(j["relevant"] is True for j in full) / len(full) if full else None,
            "none_cases": len(none),
            "not_relevant_when_none": sum(j["relevant"] is False for j in none) / len(none) if none else None,
            "errors": sum(j["status"] != "ok" for j in judged),
            "disagreements": [
                {"case": j["case"].id, "truth": j["truth"], "coverage": j["coverage"], "reason": j["reason"]}
                for j in judged
                if (j["truth"] == "full" and j["relevant"] is not True)
                or (j["truth"] == "none" and j["relevant"] is not False)
            ],
        },
        "calls": len(tap.calls),
        "avg_cost_usd": statistics.fmean(c["cost_usd"] for c in calls),
        "avg_input_tokens": statistics.fmean(c["input_tokens"] for c in calls),
        "avg_output_tokens": statistics.fmean(c["output_tokens"] for c in calls),
        "p50_latency_s": statistics.median(c["latency_s"] for c in calls),
    }


# --------------------------------------------------------------------------- report


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.0f}%"


def render(results: dict[str, Any]) -> str:
    info = results["run"]
    k = info["top_k"]
    lines = ["# Retrieval benchmark\n"]
    lines.append(
        f"Generated {info['finished']}. Embeddings: `{info['embeddings']}`. {info['cases']} answerable questions "
        f"with {info['phrases']} labelled evidence phrases, plus {info['negatives']} questions the knowledge base "
        "cannot answer (used only for the evaluator verdict check). Query = the customer's question verbatim. "
        "A phrase is *found* when it appears inside a returned passage as the agent sees it.\n"
    )
    lines.append(
        "**recall@k**: share of evidence phrases in the top k passages. **complete@k**: questions whose evidence "
        "was *all* in the top k. **MRR**: mean 1/rank of the first passage containing evidence. **chars@k**: "
        "characters of context handed to the model. **recall @ N chars**: recall when each strategy may hand over "
        "at most N characters (fair comparison across chunk sizes).\n"
    )
    first_stage = info["first_stage"]

    lines.append(f"## Chunking strategies (first stage: {first_stage})\n")
    lines.append(
        "| Strategy | Chunks | Median chars | Phrases intact | recall@4 | recall@8 | complete@4 | MRR | chars@4 "
        "| recall @ 1.5k chars | recall @ 3k chars | recall @ 6k chars | Note |"
    )
    lines.append("|---" * 13 + "|")
    for name, s in results["strategies"].items():
        m = s["metrics"]
        lines.append(
            f"| {name} | {s['chunks']} | {s['median_chars']} | {_pct(s['intact'])} | {_pct(m['recall@4'])} | "
            f"{_pct(m['recall@8'])} | {_pct(m['complete@4'])} | {m['mrr']:.2f} | {m['chars@4']:,.0f} | "
            f"{_pct(m['recall@1500chars'])} | {_pct(m['recall@3000chars'])} | {_pct(m['recall@6000chars'])} | "
            f"{s['note']} |"
        )
    lines.append("")

    lines.append("## Search mode and fusion weight (default chunker)\n")
    lines.append(
        "| First stage | recall@3 | recall@4 | recall@6 | recall@10 | recall@20 | complete@6 | MRR |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for label, m in results["modes"].items():
        lines.append(
            f"| {label} | {_pct(m['recall@3'])} | {_pct(m['recall@4'])} | {_pct(m['recall@6'])} | "
            f"{_pct(m['recall@10'])} | {_pct(m['recall@20'])} | {_pct(m['complete@6'])} | {m['mrr']:.2f} |"
        )
    lines.append("")

    m = results["modes"][first_stage]
    lines.append(f"## top-k (default chunker, {first_stage})\n")
    lines.append("| k | recall@k | complete@k | chars@k |")
    lines.append("|---|---|---|---|")
    for kk in KS:
        lines.append(
            f"| {kk} | {_pct(m[f'recall@{kk}'])} | {_pct(m[f'complete@{kk}'])} | {m[f'chars@{kk}']:,.0f} |"
        )
    lines.append("")

    if results["rerank"]:
        lines.append(f"## LLM re-ranking (default chunker, candidates from {first_stage})\n")
        lines.append(
            "The evaluator scores every candidate in the pool in the same call that grades the search, and the "
            "tool keeps the best k. The verdict columns check the evaluator's `relevant` flag against the labels: "
            "*full* = all evidence was in the pool, *none* = none was (includes the unanswerable questions).\n"
        )
        lines.append(
            "| Re-ranking | recall@3 | recall@4 | recall@6 | complete@4 | complete@6 | MRR | relevant when full "
            "| not relevant when none | avg cost / search | p50 latency |"
        )
        lines.append("|---" * 11 + "|")
        lines.append(
            f"| none ({first_stage} order) | {_pct(m['recall@3'])} | {_pct(m['recall@4'])} | {_pct(m['recall@6'])} "
            f"| {_pct(m['complete@4'])} | {_pct(m['complete@6'])} | {m['mrr']:.2f} | – | – | $0 | – |"
        )
        for r in results["rerank"]:
            rm, v = r["metrics"], r["verdict"]
            lines.append(
                f"| {r['spec']} | {_pct(rm['recall@3'])} | {_pct(rm['recall@4'])} | {_pct(rm['recall@6'])} | "
                f"{_pct(rm['complete@4'])} | {_pct(rm['complete@6'])} | {rm['mrr']:.2f} | "
                f"{_pct(v['relevant_when_full'])} of {v['full_cases']} | {_pct(v['not_relevant_when_none'])} of "
                f"{v['none_cases']} | ${r['avg_cost_usd']:.4f} | {r['p50_latency_s']:.1f}s |"
            )
        lines.append("")

    lines.append(f"## Misses (default chunker, {first_stage}, top {k}, no re-ranking)\n")
    lines.append(f"Evidence phrases not in the top {k} for the verbatim question:\n")
    for case_id, phrases in results["misses"].items():
        lines.append(f"- **{case_id}**: " + "; ".join(f"“{p}”" for p in phrases))
    lines.append("")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- main


async def _main(args: argparse.Namespace) -> int:
    settings = Settings()
    all_cases = load_dataset(args.dataset)
    cases = [c for c in all_cases if c.evidence]
    negatives = [c for c in all_cases if not c.evidence and c.expected_behavior == "cannot_verify"]
    sources = [
        (p.as_posix(), p.read_text(encoding="utf-8"))
        for p in sorted((settings.data_dir / "knowledge_base").glob("*.md"))
    ]
    embedder = CachedEmbedder(
        build_embedder(settings), Path(".data") / f"bench_embeddings_{settings.embedding_model}.npz"
    )
    first_stage = SearchConfig("hybrid", args.lexical_weight)
    sweep = [SearchConfig("vector"), SearchConfig("lexical")] + [
        SearchConfig("hybrid", w) for w in sorted({1.0, 0.5, 0.25, args.lexical_weight}, reverse=True)
    ]
    results: dict[str, Any] = {"strategies": {}, "modes": {}, "rerank": [], "misses": {}}
    try:
        for strategy in STRATEGIES:
            store, chunks = await build_store(strategy, sources, embedder)
            views = [c.content[: strategy.view_chars] for c in chunks]
            phrases = [p for case in cases for p in case.evidence]
            rankings = {
                c.id: await rank(store, embedder, first_stage, c.question, settings.rrf_k) for c in cases
            }
            results["strategies"][strategy.name] = {
                "kind": strategy.kind,
                "note": strategy.note,
                "chunks": len(chunks),
                "median_chars": int(statistics.median(len(c.content) for c in chunks)),
                "intact": sum(bool(found_phrases([p], views)) for p in phrases) / len(phrases),
                "metrics": aggregate([score_ranking(c, rankings[c.id], strategy.view_chars) for c in cases]),
            }
            print(
                f"{strategy.name}: recall@4={results['strategies'][strategy.name]['metrics']['recall@4']:.2f}"
            )
            if strategy is not STRATEGIES[0]:
                continue

            default_store, view_chars = store, strategy.view_chars
            for config in sweep:
                ranked = {
                    c.id: await rank(store, embedder, config, c.question, settings.rrf_k) for c in cases
                }
                results["modes"][config.label] = aggregate(
                    [score_ranking(c, ranked[c.id], view_chars) for c in cases]
                )
            for case in cases:
                found = found_phrases(
                    case.evidence, [c.content[:view_chars] for c in rankings[case.id][: args.top_k]]
                )
                missed = [p for i, p in enumerate(case.evidence) if i not in found]
                if missed:
                    results["misses"][case.id] = missed
            candidates = dict(rankings)

        for case in negatives:
            candidates[case.id] = await rank(
                default_store, embedder, first_stage, case.question, settings.rrf_k
            )
        for spec in [s.strip() for s in args.rerank.split(",") if s.strip()]:
            outcome = await rerank_experiment(settings, spec, [*cases, *negatives], candidates, view_chars)
            results["rerank"].append(outcome)
            print(
                f"rerank {outcome['spec']}: recall@4={outcome['metrics']['recall@4']:.2f} "
                f"cost/search=${outcome['avg_cost_usd']:.4f} errors={outcome['verdict']['errors']}"
            )
    finally:
        embedder.save()
        await embedder.aclose()

    results["run"] = {
        "finished": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "embeddings": f"{settings.embedding_provider}:{settings.embedding_model}",
        "cases": len(cases),
        "negatives": len(negatives),
        "phrases": sum(len(c.evidence) for c in cases),
        "first_stage": first_stage.label,
        "top_k": args.top_k,
        "new_embeddings": embedder.misses,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    (args.out / "report.md").write_text(render(results), encoding="utf-8")
    print(f"report: {(args.out / 'report.md').as_posix()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    defaults = Settings()
    parser = argparse.ArgumentParser(prog="retrieval-bench")
    parser.add_argument("--dataset", type=Path, default=Path("data/eval/cloudbox_support_v1.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("reports/retrieval"))
    parser.add_argument(
        "--lexical-weight",
        type=float,
        default=defaults.retrieval_lexical_weight,
        help="Keyword weight of the hybrid first stage used for the chunking table and re-ranking candidates.",
    )
    parser.add_argument("--top-k", type=int, default=defaults.retrieval_top_k, help="k for the misses list.")
    parser.add_argument(
        "--rerank",
        default="",
        help="Comma-separated evaluator re-ranking runs as model[:pool], e.g. claude-haiku-5-5:10,claude-sonnet-5-5:10",
    )
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
