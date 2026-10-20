"""Okapi BM25 for the in-process index (the Postgres store uses native full-text search)."""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "my",
        "of",
        "on",
        "or",
        "our",
        "so",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "this",
        "to",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
        "me",
        "am",
        "been",
        "being",
        "did",
    ]
)


def tokenize(text: str) -> list[str]:
    """Lowercase tokens; compound tokens (``cbx-4291``, ``rate_limit_exceeded``) also yield their parts."""
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(text.lower()):
        if token not in _STOPWORDS:
            tokens.append(token)
        if "-" in token or "_" in token:
            tokens.extend(p for p in re.split(r"[-_]", token) if p and p not in _STOPWORDS)
    return tokens


class BM25Index:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs = [Counter(tokenize(d)) for d in documents]
        self.lengths = [sum(c.values()) for c in self.docs]
        self.avg_len = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df: Counter[str] = Counter()
        for counts in self.docs:
            df.update(counts.keys())
        n = len(self.docs)
        self.idf = {term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}

    def scores(self, query: str) -> list[float]:
        terms = tokenize(query)
        out: list[float] = []
        for counts, length in zip(self.docs, self.lengths, strict=True):
            score = 0.0
            for term in terms:
                tf = counts.get(term)
                if not tf:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * length / (self.avg_len or 1))
                score += self.idf.get(term, 0.0) * tf * (self.k1 + 1) / denom
            out.append(score)
        return out
