"""Chat use-case: authentication, rate limiting, session binding, agent execution, persistence.

Shared by the JSON endpoint and the SSE streaming endpoint.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException, Request

from backend.agent.loop import AgentResult
from backend.container import Container
from backend.observability import metrics
from backend.schemas.api import ChatRequest, ChatResponse, SourceOut, ToolCallOut, UsageOut
from backend.security.auth import AuthError, Principal
from backend.storage.sessions import Session
from backend.tools.base import EventSink


class _LockRegistry:
    """Per-key locks that are discarded when no request holds or waits for them (no unbounded growth)."""

    def __init__(self) -> None:
        self._locks: dict[str, tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def hold(self, key: str) -> AsyncIterator[None]:
        lock, users = self._locks.get(key, (asyncio.Lock(), 0))
        self._locks[key] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            lock, users = self._locks[key]
            if users <= 1:
                del self._locks[key]
            else:
                self._locks[key] = (lock, users - 1)

    def __len__(self) -> int:
        return len(self._locks)


_session_locks = _LockRegistry()


def client_key(request: Request, trust_forwarded_for: bool) -> str:
    if trust_forwarded_for:
        # Azure Front Door / Container Apps ingress append the client IP; take the left-most entry.
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def authenticate(container: Container, request: Request, body_customer_id: str | None) -> Principal:
    try:
        return container.authenticator.authenticate(
            request.headers.get("authorization"),
            body_customer_id.upper() if body_customer_id else None,
            client_key(request, container.settings.trust_forwarded_for),
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


async def enforce_rate_limit(container: Container, principal: Principal, request: Request) -> None:
    key = (
        principal.subject
        if principal.authenticated
        else client_key(request, container.settings.trust_forwarded_for)
    )
    allowed, retry_after = await container.rate_limiter.check(key)
    if not allowed:
        metrics.RATE_LIMITED.inc()
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


async def load_session(container: Container, principal: Principal, session_id: str | None) -> Session:
    if session_id is None:
        return Session(session_id=uuid.uuid4().hex, owner=principal.subject)
    session = await container.sessions.get(session_id)
    # Authenticated sessions are owned by the principal; anonymous sessions are bearer capabilities.
    if session is None or (principal.authenticated and session.owner != principal.subject):
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


def bind_customer(session: Session, principal: Principal) -> None:
    target = principal.customer_id.upper() if principal.customer_id else None
    if target is None:
        return
    if session.bound_customer_id and session.bound_customer_id != target:
        raise HTTPException(status_code=409, detail="This session belongs to a different customer.")
    session.bound_customer_id = target


def to_response(result: AgentResult, session: Session, request_id: str, expose_trace: bool) -> ChatResponse:
    tool_calls = [
        ToolCallOut(
            step=c.step,
            tool=c.tool,
            status=c.status,
            latency_ms=round(c.latency_ms, 1),
            attempts=c.attempts,
            summary=c.summary,
            query=c.arguments.get("query") if c.tool != "get_customer_account" else None,
        )
        for c in result.trace.tool_calls
    ]
    return ChatResponse(
        request_id=request_id,
        session_id=session.session_id,
        execution_id=result.execution_id,
        response_type=result.response_type,
        answer=result.answer,
        sources=[SourceOut.from_evidence(e) for e in result.sources],
        activity=result.activity,
        tool_calls=tool_calls if expose_trace else [],
        evidence=result.evidence_summary,
        usage=UsageOut(
            llm_calls=len(result.trace.llm_calls),
            input_tokens=result.usage.total_input_tokens,
            output_tokens=result.usage.output_tokens,
            cache_read_tokens=result.usage.cache_read_tokens,
            estimated_cost_usd=round(result.cost_usd, 6) if result.cost_usd is not None else None,
            latency_ms=round(result.latency_ms, 1),
        ),
        stop_reason=result.stop_reason,
        warnings=result.warnings,
    )


async def run_chat(
    container: Container, request: Request, body: ChatRequest, emit: EventSink | None = None
) -> ChatResponse:
    principal = await authenticate(container, request, body.customer_id)
    await enforce_rate_limit(container, principal, request)
    request_id: str = getattr(request.state, "request_id", "unknown")

    # Serialize turns of the same session within this replica so concurrent messages cannot interleave.
    async with _session_locks.hold(body.session_id or uuid.uuid4().hex):
        session = await load_session(container, principal, body.session_id)
        bind_customer(session, principal)
        session.add_user_turn(body.message)
        result = await container.agent.run(
            session=session, principal=principal, user_message=body.message, request_id=request_id, emit=emit
        )
        await container.sessions.save(session)
        await container.traces.save(result.trace)
    return to_response(result, session, request_id, container.settings.expose_trace_in_response)
