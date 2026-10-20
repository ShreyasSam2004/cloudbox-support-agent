from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from backend.api.dependencies import get_container

router = APIRouter(tags=["health"])


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz(request: Request) -> JSONResponse:
    """Readiness: dependencies are reachable and the knowledge base is indexed."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        return JSONResponse({"status": "starting"}, status_code=503)
    checks: dict[str, str] = {}
    try:
        chunks = await get_container(request).store.chunk_count()
        checks["knowledge_base"] = "ok" if chunks > 0 else "empty"
    except Exception:
        checks["knowledge_base"] = "error"
    if container.pool is not None:
        try:
            await container.pool.fetchval("SELECT 1")
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "error"
    ready = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ready" if ready else "degraded", "checks": checks}, status_code=200 if ready else 503
    )


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
