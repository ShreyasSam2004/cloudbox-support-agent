"""Authorization boundary for customer data.

This check runs inside ``get_customer_account`` — *not* in the prompt — so a manipulated model
still cannot read another customer's account. A customer ID is accessible only if it is:

1. the authenticated principal's customer ID (verified identity), or
2. bound to the session by the trusted client (``AUTH_MODE=none`` demo/portal mode), or
3. (demo mode only, ``ALLOW_UNVERIFIED_CUSTOMER_LOOKUP=true``) typed by the *user* in this
   conversation — provenance is checked against the user's own messages, so an ID that appears
   only in a retrieved document or web page is never accessible.

A session bound to one customer can never be switched to another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.security.auth import Principal


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    view: Literal["full", "limited", "none"]
    reason: str


def authorize_customer_access(
    requested_id: str,
    *,
    principal: Principal,
    bound_customer_id: str | None,
    user_mentioned_ids: set[str],
    allow_unverified: bool,
) -> AccessDecision:
    requested = requested_id.strip().upper()

    if principal.authenticated:
        if principal.customer_id and requested == principal.customer_id.upper():
            return AccessDecision(True, "full", "authenticated customer")
        return AccessDecision(False, "none", "authenticated users can only access their own account")

    if bound_customer_id:
        if requested == bound_customer_id.upper():
            return AccessDecision(True, "full", "customer bound to session by trusted client")
        return AccessDecision(False, "none", "this session is bound to a different customer")

    if allow_unverified and requested in user_mentioned_ids:
        return AccessDecision(
            True, "limited", "customer ID provided by the user in this conversation (unverified)"
        )

    if requested in user_mentioned_ids:
        return AccessDecision(False, "none", "the customer must sign in before account data can be shown")
    return AccessDecision(
        False,
        "none",
        "this customer ID was not provided by the customer; ask the customer for their customer ID",
    )
