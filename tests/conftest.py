"""Shared fixtures.

Unit and integration tests are hermetic: the LLM is a ScriptedProvider, embeddings use the
deterministic HashingEmbedder, and the index is the in-process store built from the real corpus.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.common.clock import FixedClock
from backend.config.settings import Settings
from backend.container import Container
from backend.models.base import LLMRequest, LLMResponse, Usage
from backend.models.scripted import ScriptedProvider, ScriptStep
from backend.retrieval.embeddings import HashingEmbedder
from backend.retrieval.ingestion import IngestionPipeline
from backend.retrieval.vector_store import InMemoryVectorStore
from backend.security.auth import Principal
from backend.storage.sessions import Session

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": "test",
        "llm_provider": "scripted",
        "agent_model": "scripted-model",
        "embedding_provider": "hashing",
        "embedding_dim": 256,
        "vector_store": "memory",
        "session_store": "memory",
        "customer_store": "json",
        "trace_store": "memory",
        "web_search_provider": "fixture",
        "data_dir": DATA,
        "max_agent_steps": 6,
        "max_tool_calls": 10,
        "agent_timeout_s": 30,
        "tool_timeout_s": 5,
        "rate_limit_per_minute": 1000,
        "admin_api_key": "test-admin-key",
        "log_json": False,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture(scope="session")
def kb_store() -> InMemoryVectorStore:
    store = InMemoryVectorStore(None)
    embedder = HashingEmbedder(256)
    asyncio.run(IngestionPipeline(store, embedder).ingest_directory(DATA / "knowledge_base"))
    return store


def evaluator_says(
    relevant: bool | None = True, confidence: float = 0.9, missing: str = "", coverage: str = "full"
) -> Callable[[LLMRequest], LLMResponse]:
    def respond(request: LLMRequest) -> LLMResponse:
        labels = re.findall(r'<passage id="([^"]+)"', request.messages[-1].text)
        # Relevant: the first two candidates (fused order) are what the question needs; the rest are on topic.
        scores = [
            {"id": label, "score": (3 if relevant else 0) if i < 2 else 1} for i, label in enumerate(labels)
        ]
        payload = {
            "passage_scores": scores,
            "relevant": relevant,
            "confidence": confidence,
            "coverage": coverage,
            "missing_information": missing,
            "reason": "scripted verdict",
        }
        return LLMResponse(
            text=json.dumps(payload),
            usage=Usage(input_tokens=50, output_tokens=20),
            model="scripted-evaluator",
            provider="scripted",
        )

    return respond


def evaluator_sequence(*verdicts: Callable[[LLMRequest], LLMResponse]) -> ScriptedProvider:
    return ScriptedProvider(list(verdicts))


async def build_container(
    kb_store: InMemoryVectorStore,
    agent_script: list[ScriptStep] | Callable[[LLMRequest], LLMResponse],
    *,
    evaluator: ScriptedProvider | None = None,
    settings: Settings | None = None,
    **kwargs: Any,
) -> tuple[Container, ScriptedProvider, ScriptedProvider]:
    agent_llm = ScriptedProvider(agent_script)
    eval_llm = evaluator or ScriptedProvider(evaluator_says())
    container = await Container.create(
        settings or make_settings(),
        llm=agent_llm,
        evaluator_llm=eval_llm,
        embedder=HashingEmbedder(256),
        store=kb_store,
        clock=FixedClock(NOW),
        **kwargs,
    )
    return container, agent_llm, eval_llm


def new_session(customer_id: str | None = None, *messages: str) -> Session:
    session = Session(session_id=uuid.uuid4().hex, owner="test", bound_customer_id=customer_id)
    for message in messages:
        session.add_user_turn(message)
    return session


def anonymous(customer_id: str | None = None) -> Principal:
    return Principal(subject="test", customer_id=customer_id, authenticated=False)


def tool_results_in(request: LLMRequest) -> list[dict[str, Any]]:
    """All tool-result payloads the model was shown in this request, decoded."""
    out: list[dict[str, Any]] = []
    for message in request.messages:
        for block in message.content:
            if getattr(block, "type", None) == "tool_result":
                out.append(json.loads(block.content))  # type: ignore[union-attr]
    return out
