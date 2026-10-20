from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from backend.container import Container


def get_container(request: Request) -> Container:
    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Service is starting.")
    return container


def require_admin(request: Request) -> None:
    container = get_container(request)
    expected = container.settings.admin_api_key
    provided = request.headers.get("x-admin-key", "")
    if expected is None or not hmac.compare_digest(provided, expected.get_secret_value()):
        raise HTTPException(status_code=404, detail="Not found.")
