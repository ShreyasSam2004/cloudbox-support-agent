"""HTTP middleware: request IDs, security headers, request-size limits."""

from __future__ import annotations

import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.observability.logging import bind_context, clear_context

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Cache-Control": "no-store",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else f"req_{uuid.uuid4().hex[:20]}"
        request.state.request_id = request_id
        clear_context()
        bind_context(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, max_bytes: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        length = request.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > self.max_bytes):
            return JSONResponse(
                {"error": "payload_too_large", "message": f"Request body exceeds {self.max_bytes} bytes."},
                status_code=413,
            )
        return await call_next(request)


class FrontDoorGuardMiddleware(BaseHTTPMiddleware):
    """Accept API traffic only from *our* Azure Front Door profile.

    The Container App ingress is reachable from the internet; Front Door stamps every forwarded request
    with ``X-Azure-FDID`` (the profile's unique ID). Requests without the right ID — e.g. someone hitting
    the *.azurecontainerapps.io FQDN directly to bypass the WAF — are rejected. Health probes come from
    the platform directly and are exempt.
    """

    def __init__(self, app: object, front_door_id: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.front_door_id = front_door_id.lower()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in ("/healthz", "/readyz"):
            return await call_next(request)
        if request.headers.get("x-azure-fdid", "").lower() != self.front_door_id:
            return JSONResponse(
                {"error": "forbidden", "message": "Direct access is not allowed."}, status_code=403
            )
        return await call_next(request)
