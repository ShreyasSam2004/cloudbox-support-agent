"""Web search providers.

* ``TavilyWebSearchProvider`` — production (API key from Azure Key Vault).
* ``FixtureWebSearchProvider`` — hermetic, deterministic corpus for tests and the benchmark.
* ``DisabledWebSearchProvider`` — environments where outbound web search is not allowed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import BaseModel

from backend.retrieval.bm25 import BM25Index
from backend.tools.base import ToolError


class WebResult(BaseModel):
    url: str
    title: str
    content: str
    published: str | None = None


class WebSearchProvider(Protocol):
    name: str

    async def search(self, query: str, max_results: int) -> list[WebResult]: ...


class FixtureWebSearchProvider:
    name = "fixture"

    def __init__(self, path: Path) -> None:
        self._pages = [WebResult.model_validate(p) for p in json.loads(path.read_text(encoding="utf-8"))]
        self._index = BM25Index([f"{p.title}\n{p.title}\n{p.content}" for p in self._pages])

    async def search(self, query: str, max_results: int) -> list[WebResult]:
        scores = self._index.scores(query)
        ranked = sorted(range(len(scores)), key=lambda i: -scores[i])
        return [self._pages[i] for i in ranked[:max_results] if scores[i] > 1.0]


class TavilyWebSearchProvider:
    name = "tavily"

    def __init__(self, api_key: str, timeout_s: float = 15.0) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://api.tavily.com",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
        )

    async def search(self, query: str, max_results: int) -> list[WebResult]:
        try:
            response = await self._client.post(
                "/search",
                json={
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                    "include_answer": False,
                },
            )
        except httpx.TransportError as exc:
            raise ToolError(
                "web_search_unavailable", "The web search provider is unreachable.", retryable=True
            ) from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise ToolError(
                "web_search_unavailable", f"Web search provider error {response.status_code}.", retryable=True
            )
        if response.status_code >= 400:
            raise ToolError("web_search_failed", f"Web search request rejected ({response.status_code}).")
        return [
            WebResult(
                url=item.get("url", ""),
                title=item.get("title", ""),
                content=item.get("content", ""),
                published=item.get("published_date"),
            )
            for item in response.json().get("results", [])
        ]


class DisabledWebSearchProvider:
    name = "disabled"

    async def search(self, query: str, max_results: int) -> list[WebResult]:
        raise ToolError("web_search_disabled", "Web search is not available in this environment.")
