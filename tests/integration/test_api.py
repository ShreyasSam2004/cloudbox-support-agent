"""HTTP API tests (FastAPI app with the scripted model injected through the container factory)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from backend.api.app import create_app
from backend.common.clock import FixedClock
from backend.config.settings import Settings
from backend.container import Container
from backend.models.base import LLMRequest, LLMResponse
from backend.models.scripted import ScriptedProvider, text_response, tool_response
from backend.retrieval.embeddings import HashingEmbedder
from tests.conftest import NOW, evaluator_says, make_settings


def agent_script(request: LLMRequest) -> LLMResponse:
    """Searches once, then answers citing the first passage."""
    results = [b for m in request.messages for b in m.content if getattr(b, "type", "") == "tool_result"]
    if not results:
        return tool_response(("search_knowledge_base", {"query": request.messages[-1].text}))
    obs = json.loads(results[-1].content)  # type: ignore[union-attr]
    return text_response(f"TYPE: answer\nHere is what I found [{obs['results'][0]['evidence_id']}].")


@pytest.fixture
async def client_factory(kb_store) -> AsyncIterator[Callable[..., Any]]:  # type: ignore[no-untyped-def]
    apps: list[Any] = []

    async def make(settings: Settings | None = None, script: Any = agent_script) -> httpx.AsyncClient:
        async def factory(s: Settings) -> Container:
            return await Container.create(
                s,
                llm=ScriptedProvider(script),
                evaluator_llm=ScriptedProvider(evaluator_says()),
                embedder=HashingEmbedder(256),
                store=kb_store,
                clock=FixedClock(NOW),
            )

        app = create_app(settings or make_settings(), container_factory=factory)
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        apps.append(lifespan)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    yield make
    for lifespan in apps:
        await lifespan.__aexit__(None, None, None)


async def test_chat_returns_answer_sources_and_safe_trace(client_factory) -> None:  # type: ignore[no-untyped-def]
    client = await client_factory()
    response = await client.post("/api/v1/chat", json={"message": "Where are my invoices?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["response_type"] == "answer"
    assert body["sources"][0]["origin"] == "internal_kb"
    assert body["sources"][0]["label"] == "CloudBox knowledge base"
    assert body["tool_calls"][0]["tool"] == "search_knowledge_base"
    assert body["usage"]["llm_calls"] == 3  # 2 agent steps + 1 evaluator call
    assert body["evidence"]["grounded"] is True
    assert response.headers["X-Request-ID"] == body["request_id"]
    # No hidden reasoning or raw prompts in the payload.
    serialized = json.dumps(body)
    assert "Working method" not in serialized and "system_dynamic" not in serialized


async def test_session_continuity_and_history(client_factory) -> None:  # type: ignore[no-untyped-def]
    client = await client_factory()
    first = (await client.post("/api/v1/chat", json={"message": "Hi, my customer ID is C1002"})).json()
    sid = first["session_id"]
    second = await client.post("/api/v1/chat", json={"session_id": sid, "message": "Where are my invoices?"})
    assert second.json()["session_id"] == sid
    history = (await client.get(f"/api/v1/sessions/{sid}")).json()
    assert [t["role"] for t in history["turns"]] == ["user", "assistant", "user", "assistant"]


async def test_session_cannot_switch_customer(client_factory) -> None:  # type: ignore[no-untyped-def]
    client = await client_factory()
    first = (await client.post("/api/v1/chat", json={"customer_id": "C1001", "message": "hello"})).json()
    switched = await client.post(
        "/api/v1/chat", json={"session_id": first["session_id"], "customer_id": "C1004", "message": "hi"}
    )
    assert switched.status_code == 409


async def test_unknown_session_and_validation(client_factory) -> None:  # type: ignore[no-untyped-def]
    client = await client_factory()
    assert (
        await client.post("/api/v1/chat", json={"session_id": "0" * 32, "message": "x"})
    ).status_code == 404
    bad = await client.post("/api/v1/chat", json={"message": ""})
    assert bad.status_code == 422
    assert bad.json()["error"] == "invalid_request"
    extra = await client.post("/api/v1/chat", json={"message": "x", "role": "system"})
    assert extra.status_code == 422
    assert (
        await client.post("/api/v1/chat", json={"message": "x", "customer_id": "DROP TABLE"})
    ).status_code == 422


async def test_body_size_limit_and_security_headers(client_factory) -> None:  # type: ignore[no-untyped-def]
    client = await client_factory(make_settings(max_request_bytes=200))
    too_big = await client.post(
        "/api/v1/chat",
        content=json.dumps({"message": "x" * 500}),
        headers={"content-type": "application/json"},
    )
    assert too_big.status_code == 413
    health = await client.get("/healthz")
    assert health.headers["X-Content-Type-Options"] == "nosniff"
    assert health.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in health.headers["Content-Security-Policy"]


async def test_rate_limiting(client_factory) -> None:  # type: ignore[no-untyped-def]
    client = await client_factory(make_settings(rate_limit_per_minute=2))
    codes = [(await client.post("/api/v1/chat", json={"message": "invoices"})).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


async def test_jwt_mode_requires_token(client_factory) -> None:  # type: ignore[no-untyped-def]
    client = await client_factory(make_settings(auth_mode="jwt", jwt_hs256_secret="x" * 40))
    response = await client.post("/api/v1/chat", json={"message": "hi"})
    assert response.status_code == 401


async def test_streaming_endpoint_emits_activity_then_final(client_factory) -> None:  # type: ignore[no-untyped-def]
    client = await client_factory()
    events: list[tuple[str, dict[str, Any]]] = []
    async with client.stream("POST", "/api/v1/chat/stream", json={"message": "invoices"}) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        event = None
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event:
                events.append((event, json.loads(line[6:])))
    kinds = [e for e, _ in events]
    assert kinds[-1] == "final"
    assert "activity" in kinds
    labels = [d["label"] for e, d in events if e == "activity"]
    assert "Searching CloudBox knowledge base…" in labels
    assert events[-1][1]["response_type"] == "answer"


async def test_admin_trace_requires_key(client_factory) -> None:  # type: ignore[no-untyped-def]
    client = await client_factory()
    body = (await client.post("/api/v1/chat", json={"message": "invoices"})).json()
    path = f"/api/v1/admin/traces/{body['execution_id']}"
    assert (await client.get(path)).status_code == 404
    trace = await client.get(path, headers={"X-Admin-Key": "test-admin-key"})
    assert trace.status_code == 200
    assert trace.json()["tool_calls"][0]["tool"] == "search_knowledge_base"


async def test_health_and_readiness(client_factory) -> None:  # type: ignore[no-untyped-def]
    client = await client_factory()
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    ready = await client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["checks"]["knowledge_base"] == "ok"
    assert (await client.get("/metrics")).status_code == 200


async def test_front_door_guard_blocks_direct_access(client_factory) -> None:  # type: ignore[no-untyped-def]
    client = await client_factory(make_settings(front_door_id="11111111-2222-3333-4444-555555555555"))
    direct = await client.post("/api/v1/chat", json={"message": "invoices"})
    assert direct.status_code == 403
    via_fd = await client.post(
        "/api/v1/chat",
        json={"message": "invoices"},
        headers={"X-Azure-FDID": "11111111-2222-3333-4444-555555555555"},
    )
    assert via_fd.status_code == 200
    assert (await client.get("/healthz")).status_code == 200  # platform probes are exempt


async def test_session_lock_registry_does_not_grow(client_factory) -> None:  # type: ignore[no-untyped-def]
    from backend.api.service import _session_locks

    client = await client_factory()
    for _ in range(3):
        await client.post("/api/v1/chat", json={"message": "invoices"})
    assert len(_session_locks) == 0
