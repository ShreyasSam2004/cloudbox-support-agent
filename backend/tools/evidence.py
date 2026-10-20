"""Evidence ledger: every item the agent sees gets a short, stable, citable ID.

``K#`` internal knowledge-base passages, ``W#`` public web results, ``A#`` customer account records.
The same underlying item (same chunk, URL or account) keeps its ID for the whole execution, so
repeated searches do not create duplicate citations.
"""

from __future__ import annotations

from typing import Any

from backend.schemas.domain import Evidence, SourceOrigin

_PREFIX = {
    SourceOrigin.INTERNAL_KB: "K",
    SourceOrigin.PUBLIC_WEB: "W",
    SourceOrigin.CUSTOMER_ACCOUNT: "A",
}


class EvidenceLedger:
    def __init__(self) -> None:
        self._by_id: dict[str, Evidence] = {}
        self._by_key: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def register(
        self,
        key: str,
        origin: SourceOrigin,
        *,
        title: str,
        snippet: str,
        doc_id: str | None = None,
        section: str | None = None,
        url: str | None = None,
        score: float | None = None,
        metadata: dict[str, Any] | None = None,
        content: str = "",
    ) -> Evidence:
        existing = self._by_key.get(key)
        if existing is not None:
            return self._by_id[existing]
        prefix = _PREFIX[origin]
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        evidence = Evidence(
            evidence_id=f"{prefix}{self._counters[prefix]}",
            origin=origin,
            title=title,
            snippet=snippet,
            doc_id=doc_id,
            section=section,
            url=url,
            score=score,
            metadata=metadata or {},
            content=content,
        )
        self._by_id[evidence.evidence_id] = evidence
        self._by_key[key] = evidence.evidence_id
        return evidence

    def get(self, evidence_id: str) -> Evidence | None:
        return self._by_id.get(evidence_id.upper())

    def all(self) -> list[Evidence]:
        return list(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)
