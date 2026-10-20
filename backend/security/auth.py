"""Authentication.

``AUTH_MODE=none`` (local/dev only — refused in prod by settings validation): the caller is
anonymous; a ``customer_id`` in the request body is treated as asserted by a trusted portal.

``AUTH_MODE=jwt``: a bearer JWT is required and verified (JWKS URL from the identity provider, or an
HS256 secret for local testing). The customer identity comes **only** from the token's claim; a
``customer_id`` in the body must match it or the request is rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient

from backend.config.settings import Settings


@dataclass(frozen=True)
class Principal:
    subject: str
    customer_id: str | None
    authenticated: bool
    """True only when identity was cryptographically verified (JWT)."""


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


class Authenticator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwks = PyJWKClient(settings.jwt_jwks_url) if settings.jwt_jwks_url else None

    def authenticate(
        self, authorization: str | None, body_customer_id: str | None, client_key: str
    ) -> Principal:
        if self._settings.auth_mode == "none":
            return Principal(subject=f"anon:{client_key}", customer_id=body_customer_id, authenticated=False)

        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthError("missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        claims = self._decode(token)
        customer_id = claims.get(self._settings.jwt_customer_claim)
        if body_customer_id and body_customer_id != customer_id:
            raise AuthError("customer_id does not match the authenticated identity", status_code=403)
        return Principal(
            subject=str(claims.get("sub", "unknown")),
            customer_id=str(customer_id) if customer_id else None,
            authenticated=True,
        )

    def _decode(self, token: str) -> dict[str, Any]:
        try:
            if self._jwks is not None:
                key = self._jwks.get_signing_key_from_jwt(token).key
                algorithms = ["RS256", "ES256"]
            elif self._settings.jwt_hs256_secret is not None:
                key = self._settings.jwt_hs256_secret.get_secret_value()
                algorithms = ["HS256"]
            else:
                raise AuthError("JWT auth is enabled but no JWKS URL or HS256 secret is configured", 500)
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=algorithms,
                audience=self._settings.jwt_audience,
                issuer=self._settings.jwt_issuer,
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"invalid token: {type(exc).__name__}") from exc
        return claims
