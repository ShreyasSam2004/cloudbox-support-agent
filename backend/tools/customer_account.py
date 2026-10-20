"""Tool 3 — ``get_customer_account``: the customer's own account record.

The authorization decision (``security/authorization.py``) is made here, in code, on every call.
The record is rendered as *data only* (timestamps, amounts, statuses) — no policy conclusions are
precomputed; interpreting the record against policy is the agent's job.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import Field

from backend.schemas.domain import CustomerAccount, SourceOrigin
from backend.security.authorization import authorize_customer_access
from backend.security.content_safety import mask_email
from backend.storage.customers import CustomerRepository
from backend.tools.base import Tool, ToolContext, ToolError, ToolInput, ToolOutput


class GetCustomerAccountInput(ToolInput):
    customer_id: str = Field(
        pattern=r"^[Cc]\d{3,6}$",
        description="The customer ID of the customer you are talking to (format C followed by digits, e.g. C1042).",
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def render_account(account: CustomerAccount, *, view: str, now: datetime) -> dict[str, Any]:
    sub = account.subscription
    rendered: dict[str, Any] = {
        "as_of": _iso(now),
        "customer_id": account.customer_id,
        "organization": account.organization_name,
        "subscription": {
            "plan": sub.plan,
            "billing_cycle": sub.billing_cycle,
            "status": sub.status,
            "seats": sub.seats,
            "price_usd": sub.price_usd,
            "started_at": _iso(sub.started_at),
            "current_period_start": _iso(sub.current_period_start),
            "current_period_end": _iso(sub.current_period_end),
            "renewal_at": _iso(sub.renewal_at),
            "cancel_requested_at": _iso(sub.cancel_requested_at),
            "cancel_effective_at": _iso(sub.cancel_effective_at),
            "trial_ends_at": _iso(sub.trial_ends_at),
            "payment_method_on_file": sub.payment_method_on_file,
            "payment_failure": sub.payment_failure,
            "add_ons": sub.add_ons,
        },
        "recent_charges": [
            {
                "charge_id": c.charge_id,
                "created_at": _iso(c.created_at),
                "amount_usd": c.amount_usd,
                "status": c.status,
                "kind": c.kind,
                "invoice_id": c.invoice_id,
                "description": c.description,
            }
            for c in sorted(account.charges, key=lambda c: c.created_at, reverse=True)[:10]
        ],
        "usage": account.usage.model_dump(exclude_defaults=True),
        "security": account.security.model_dump(),
    }
    rendered["subscription"] = {k: v for k, v in rendered["subscription"].items() if v not in (None, [], {})}
    if account.contract is not None:
        rendered["contract"] = {
            "contract_id": account.contract.contract_id,
            "term_start": _iso(account.contract.term_start),
            "term_end": _iso(account.contract.term_end),
            "annual_value_usd": account.contract.annual_value_usd,
            "notice_period_days": account.contract.notice_period_days,
            "account_manager": account.contract.account_manager,
        }
    if account.notes:
        rendered["notes"] = account.notes
    if view == "full":
        rendered["contact"] = {
            "name": account.contact_name,
            "role": account.contact_role,
            "email": mask_email(account.contact_email),
        }
    return rendered


class GetCustomerAccountTool(Tool):
    name = "get_customer_account"
    description = (
        "Retrieve the account record of the customer you are talking to: plan, subscription and cancellation "
        "status with UTC timestamps, recent charges (including pending authorization holds), API usage and "
        "429 breakdown, sign-in/lock status and contract terms. Use it when the right answer depends on this "
        "customer's own situation. Only works for the customer's own ID (the authenticated customer, or an ID "
        "the customer typed in this conversation). Result has evidence ID A1."
    )
    input_model = GetCustomerAccountInput
    activity_label = "Checking customer account…"

    def __init__(self, repository: CustomerRepository) -> None:
        self.repository = repository

    async def run(self, args: GetCustomerAccountInput, ctx: ToolContext) -> ToolOutput:
        customer_id = args.customer_id.upper()
        decision = authorize_customer_access(
            customer_id,
            principal=ctx.principal,
            bound_customer_id=ctx.session.bound_customer_id,
            user_mentioned_ids=set(ctx.session.mentioned_customer_ids),
            allow_unverified=ctx.settings.allow_unverified_customer_lookup,
        )
        if not decision.allowed:
            raise ToolError("not_authorized", f"Access denied: {decision.reason}.")

        account = await self.repository.get(customer_id)
        if account is None:
            raise ToolError(
                "customer_not_found",
                f"No account exists with customer ID {customer_id}. Ask the customer to check it.",
            )
        rendered = render_account(account, view=decision.view, now=ctx.now)
        evidence = ctx.ledger.register(
            f"account:{customer_id}",
            SourceOrigin.CUSTOMER_ACCOUNT,
            title=f"Your CloudBox account ({customer_id})",
            snippet=f"{account.subscription.plan.title()} plan, status {account.subscription.status}",
            metadata={"customer_id": customer_id, "view": decision.view},
            content=json.dumps(rendered, default=str),
        )
        ctx.session.last_account_lookup = customer_id
        observation = {
            "evidence_id": evidence.evidence_id,
            "access": decision.view,
            "account": rendered,
            "note": "Confidential account data for this customer only. Timestamps are UTC.",
        }
        summary = f"account {customer_id}: {account.subscription.plan} plan, {account.subscription.status}"
        return ToolOutput(observation=observation, summary=summary, evidence_ids=[evidence.evidence_id])
