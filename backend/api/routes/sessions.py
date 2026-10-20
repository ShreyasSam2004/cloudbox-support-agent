from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Request

from backend.api.dependencies import get_container, require_admin
from backend.api.service import authenticate
from backend.schemas.api import SessionOut, SessionTurnOut
from backend.schemas.trace import AgentTrace

router = APIRouter(prefix="/api/v1", tags=["sessions"])


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(request: Request, session_id: str = Path(pattern=r"^[0-9a-f]{32}$")) -> SessionOut:
    container = get_container(request)
    principal = await authenticate(container, request, None)
    session = await container.sessions.get(session_id)
    if session is None or (principal.authenticated and session.owner != principal.subject):
        raise HTTPException(status_code=404, detail="Session not found.")
    return SessionOut(
        session_id=session.session_id,
        customer_id=session.bound_customer_id,
        turns=[
            SessionTurnOut(
                role=t.role, content=t.content, response_type=t.response_type, source_titles=t.source_titles
            )
            for t in session.turns
        ],
    )


@router.get("/admin/traces/{execution_id}", response_model=AgentTrace)
async def get_trace(request: Request, execution_id: str = Path(pattern=r"^exec_[0-9a-f]{24}$")) -> AgentTrace:
    """Operator-only trajectory inspection (requires ``X-Admin-Key``). Contains actions, not reasoning."""
    require_admin(request)
    trace = await get_container(request).traces.get(execution_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found.")
    return trace
