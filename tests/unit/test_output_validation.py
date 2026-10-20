from __future__ import annotations

import pytest

from backend.agent.output import WEB_NOTE, validate_output
from backend.schemas.domain import SourceOrigin
from backend.tools.evidence import EvidenceLedger


@pytest.fixture
def ledger() -> EvidenceLedger:
    led = EvidenceLedger()
    led.register("c1", SourceOrigin.INTERNAL_KB, title="Refund Policy", snippet="...")
    led.register("c2", SourceOrigin.INTERNAL_KB, title="Billing Policy", snippet="...")
    led.register("https://x", SourceOrigin.PUBLIC_WEB, title="Blog", snippet="...", url="https://x")
    led.register("account:C1", SourceOrigin.CUSTOMER_ACCOUNT, title="Account", snippet="...")
    return led


def test_ledger_ids_are_stable_and_prefixed(ledger: EvidenceLedger) -> None:
    again = ledger.register("c1", SourceOrigin.INTERNAL_KB, title="Refund Policy", snippet="...")
    assert again.evidence_id == "K1"
    assert [e.evidence_id for e in ledger.all()] == ["K1", "K2", "W1", "A1"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("TYPE: answer\nYes [K1].", "answer"),
        ("**TYPE: clarification**\nWhich plan are you on?", "clarification"),
        ("type: cannot_verify\nI can't confirm that.", "cannot_verify"),
        ("Could you share your customer ID?", "clarification"),
        ("Refunds take 5-10 days [K1].", "answer"),
    ],
)
def test_response_type_parsing(ledger: EvidenceLedger, raw: str, expected: str) -> None:
    assert validate_output(raw, ledger).response_type == expected


def test_type_line_is_stripped(ledger: EvidenceLedger) -> None:
    out = validate_output("TYPE: answer\nYou are eligible [K1].", ledger)
    assert out.text == "You are eligible [K1]."


def test_unknown_citations_removed_and_reported(ledger: EvidenceLedger) -> None:
    out = validate_output("TYPE: answer\nA [K1, K9]. B [W7]. C [a1].", ledger)
    assert out.cited_ids == ["K1", "A1"]
    assert out.invalid_citations == ["K9", "W7"]
    assert "[K1]" in out.text and "W7" not in out.text
    assert "invalid_citations_removed" in out.warnings


def test_web_citation_requires_external_label(ledger: EvidenceLedger) -> None:
    out = validate_output("TYPE: answer\nUse jitter [W1].", ledger)
    assert WEB_NOTE in out.text
    labelled = validate_output(
        "TYPE: answer\nGeneral guidance from public sources, not CloudBox policy [W1].", ledger
    )
    assert WEB_NOTE not in labelled.text


def test_secrets_and_foreign_emails_redacted(ledger: EvidenceLedger) -> None:
    out = validate_output(
        "TYPE: answer\nKey cbx_live_ABCDEFGH1234 email h.scorpio@globex.example or billing@cloudbox.example [K1]",
        ledger,
    )
    assert "cbx_live_ABCDEFGH1234" not in out.text
    assert "h.scorpio@globex.example" not in out.text
    assert "billing@cloudbox.example" in out.text
    assert out.redactions == 2


def test_internal_tags_and_empty_reply(ledger: EvidenceLedger) -> None:
    out = validate_output("<think>secret plan</think>", ledger)
    assert out.response_type == "cannot_verify"
    assert "secret plan" not in out.text  # reasoning blocks are removed entirely, never shown
    assert "support@cloudbox.example" in out.text
