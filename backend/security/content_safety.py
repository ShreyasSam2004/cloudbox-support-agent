"""Guards for untrusted content entering the model and sensitive content leaving the system.

* :func:`detect_injection` flags instruction-like text in retrieved documents and web pages.
  It is a heuristic *signal*, not the defence: authorization lives in the tools, and the model is
  told that retrieved content is data. Flagged passages are labelled in the observation.
* :func:`find_pii` blocks customer data from being sent to the external web-search provider.
* :func:`redact_secrets` scrubs credentials from model output before it reaches the customer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override_instructions",
        re.compile(
            r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all|your)\b.{0,20}\b(instructions|rules|prompt)",
            re.I | re.S,
        ),
    ),
    (
        "system_impersonation",
        re.compile(r"\b(system (notice|override|prompt|message)|you are now|new instructions)\b", re.I),
    ),
    (
        "assistant_targeting",
        re.compile(
            r"\b(ai assistants?|support bots?|language models?|llms?)\b.{0,40}\b(reading|must|should|tell|do not)\b",
            re.I | re.S,
        ),
    ),
    (
        "credential_request",
        re.compile(
            r"\b(email|send|paste|share|enter)\b.{0,40}\b(password|api key|recovery code|credentials?)\b",
            re.I | re.S,
        ),
    ),
    (
        "tool_steering",
        re.compile(
            r"\b(call|use|invoke)\b.{0,20}\b(get_customer_account|search_knowledge_base|web_search)\b",
            re.I | re.S,
        ),
    ),
    ("hidden_markup", re.compile(r"<!--.*?-->", re.S)),
)

_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("customer_id", re.compile(r"\bC\d{3,6}\b", re.I)),
    ("api_key", re.compile(r"\bcbx_(?:live|test)_[A-Za-z0-9]{4,}")),
    ("card_number", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("phone", re.compile(r"\+?\d[\d\s().-]{8,}\d")),
    ("invoice_id", re.compile(r"\bINV-\d+-\d+\b", re.I)),
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcbx_(?:live|test)_[A-Za-z0-9]{8,}"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:ghp|gho|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


@dataclass(frozen=True)
class InjectionFinding:
    suspected: bool
    signals: list[str]


def detect_injection(text: str) -> InjectionFinding:
    signals = [name for name, pattern in _INJECTION_PATTERNS if pattern.search(text)]
    # A lone HTML comment is common and harmless; require it to co-occur with another signal.
    suspected = bool(signals) and signals != ["hidden_markup"]
    return InjectionFinding(suspected=suspected, signals=signals)


def strip_hidden_markup(text: str) -> str:
    """Remove HTML comments/scripts from external web content (invisible to humans, visible to models)."""
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", text)


def find_pii(text: str) -> list[str]:
    return [name for name, pattern in _PII_PATTERNS if pattern.search(text)]


def redact_secrets(text: str) -> tuple[str, int]:
    count = 0
    for pattern in _SECRET_PATTERNS:
        text, n = pattern.subn("[REDACTED]", text)
        count += n
    return text, count


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}"
