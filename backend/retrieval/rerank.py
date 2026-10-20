"""Re-ranking of a retrieved candidate pool with the retrieval evaluator's per-passage scores.

Hybrid search (RRF) is good at *recall* — the passage that answers the question is usually somewhere
in the top 10-20 — but its order is driven by surface similarity. The evaluator reads the passages
anyway, so it also scores each one (0-3) and the search tool keeps the best ``top_k``. Ties keep the
fused order; passages the evaluator scored 0 (unrelated) are dropped.
"""

from __future__ import annotations

import re

CANDIDATE_PREFIX = "cand-"
_LABEL_RE = re.compile(rf"\b{CANDIDATE_PREFIX}(\d+)\b", re.IGNORECASE)  # models sometimes write "Cand-3"

MIN_KEEP_WHEN_NOTHING_RELEVANT = 2
"""If every candidate is scored 0, still show the top fused results so the agent sees what exists."""

_UNSCORED = 1  # a passage the evaluator skipped is treated as "same topic", never dropped


def candidate_label(index: int) -> str:
    return f"{CANDIDATE_PREFIX}{index}"


def rerank(labels: list[str], scores: dict[str, int], top_k: int) -> list[str]:
    """Return up to ``top_k`` labels, best first. ``labels`` must be in fused (retrieval) order."""
    if not scores:
        return labels[:top_k]

    def score(label: str) -> int:
        return scores.get(label, _UNSCORED)

    ordered = sorted(labels, key=lambda label: -score(label))  # stable: ties keep fused order
    kept = [label for label in ordered if score(label) > 0][:top_k]
    return kept or labels[: min(MIN_KEEP_WHEN_NOTHING_RELEVANT, top_k)]


def relabel(text: str, mapping: dict[str, str]) -> str:
    """Replace candidate labels in evaluator prose with evidence IDs (or a neutral phrase if not kept)."""
    return _LABEL_RE.sub(
        lambda m: mapping.get(f"{CANDIDATE_PREFIX}{m.group(1)}", "a lower-ranked passage"), text
    )
