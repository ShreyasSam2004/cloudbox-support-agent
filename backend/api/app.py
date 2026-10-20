"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend import __version__
from backend.api.middleware import (
    BodySizeLimitMiddleware,
    FrontDoorGuardMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from backend.api.routes import chat, health, sessions
from backend.config.settings import Settings, get_settings
from backend.container import Container
from backend.observability.logging import configure_logging, get_logger
from backend.observability.telemetry import configure_telemetry

log = get_logger(__name__)

ContainerFactory = Callable[[Settings], Awaitable[Container]]


def create_app(
    settings: Settings | None = None, container_factory: ContainerFactory | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    configure_telemetry(settings)
    factory = container_factory or Container.create

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = await factory(settings)
        try:
            yield
        finally:
            await app.state.container.aclose()

    app = FastAPI(
        title="CloudBox Support Agent API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    # Middleware order: the last added runs first.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    if settings.front_door_id:
        app.add_middleware(FrontDoorGuardMiddleware, front_door_id=settings.front_door_id)
    app.add_middleware(RequestContextMiddleware)

    def _request_id(request: Request) -> str | None:
        return getattr(request.state, "request_id", None)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            {"error": "http_error", "message": exc.detail, "request_id": _request_id(request)},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [
            {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()[:10]
        ]
        return JSONResponse(
            {
                "error": "invalid_request",
                "message": "Request validation failed.",
                "details": problems,
                "request_id": _request_id(request),
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("api.unhandled_error", path=request.url.path)
        return JSONResponse(
            {
                "error": "internal_error",
                "message": "An internal error occurred.",
                "request_id": _request_id(request),
            },
            status_code=500,
        )

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(sessions.router)
    return app
