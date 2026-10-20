"""Output validation for the agent's terminal reply.

Deterministic post-processing (no decisions about *what* to answer):

* parse the ``TYPE:`` line (tolerant of formatting variations; inferred when missing);
* keep only citations that refer to evidence actually retrieved in this execution — any other
  ``[K9]`` is removed and counted (a fabricated citation is a hallucination signal);
* enforce the "not CloudBox policy" label when public-web evidence is cited;
* redact credentials and stray email addresses; strip leaked internal tags; cap length.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.security.content_safety import redact_secrets
from backend.tools.evidence import EvidenceLedger

RESPONSE_TYPES = ("answer", "clarification", "cannot_verify")
MAX_REPLY_CHARS = 6000

_TYPE_RE = re.compile(
    r"^\s*[*_`#>\s]*(?:response[_ ]?)?type\s*[:=]\s*[*_`\s]*(answer|clarification|cannot[_ ]verify)\b[*_`]*[ \t]*\n?",
    re.I,
)
_CITATION_RE = re.compile(r"\[\s*([KWA]\d+(?:\s*[,;]\s*[KWA]\d+)*)\s*\]", re.I)
_REASONING_BLOCK_RE = re.compile(r"<(think|thinking)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_INTERNAL_TAG_RE = re.compile(r"</?(?:think|thinking|system|tool_call|function_calls?)[^>]*>", re.I)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@([\w-]+(?:\.[\w-]+)+)\b")
_WEB_LABEL_RE = re.compile(
    r"not (?:official )?cloudbox policy|public (?:web|sources?)|external (?:source|information|guidance)|third[- ]party",
    re.I,
)

WEB_NOTE = "_Note: items cited as [W#] come from public web sources and are not official CloudBox policy._"
_ALLOWED_EMAIL_DOMAINS = ("cloudbox.example",)


@dataclass
class ValidatedOutput:
    response_type: str
    text: str
    cited_ids: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    redactions: int = 0

    @property
    def has_citations(self) -> bool:
        return bool(self.cited_ids)


def _infer_type(text: str) -> str:
    last = text.strip().splitlines()[-1] if text.strip() else ""
    return "clarification" if last.rstrip().endswith("?") and not _CITATION_RE.search(text) else "answer"


def validate_output(raw: str, ledger: EvidenceLedger) -> ValidatedOutput:
    warnings: list[str] = []
    text = _INTERNAL_TAG_RE.sub("", _REASONING_BLOCK_RE.sub("", raw or "")).strip()

    match = _TYPE_RE.match(text)
    if match:
        response_type = match.group(1).lower().replace(" ", "_")
        text = text[match.end() :].strip()
    else:
        response_type = _infer_type(text)
        warnings.append("missing_type_line")

    cited: list[str] = []
    invalid: list[str] = []

    def _replace(m: re.Match[str]) -> str:
        valid: list[str] = []
        for raw_id in re.split(r"\s*[,;]\s*", m.group(1)):
            eid = raw_id.strip().upper()
            if ledger.get(eid) is not None:
                valid.append(eid)
                if eid not in cited:
                    cited.append(eid)
            else:
                invalid.append(eid)
        return f"[{', '.join(valid)}]" if valid else ""

    text = _CITATION_RE.sub(_replace, text)
    if invalid:
        warnings.append("invalid_citations_removed")
        text = re.sub(r"[ \t]+([.,;:])", r"\1", text)

    if any(c.startswith("W") for c in cited) and not _WEB_LABEL_RE.search(text):
        text = f"{text}\n\n{WEB_NOTE}"
        warnings.append("web_disclaimer_added")

    text, secret_hits = redact_secrets(text)

    email_redactions = 0

    def _email(m: re.Match[str]) -> str:
        nonlocal email_redactions
        if m.group(1).lower().endswith(_ALLOWED_EMAIL_DOMAINS) or "***" in m.group(0):
            return m.group(0)
        email_redactions += 1
        return "[email redacted]"

    text = _EMAIL_RE.sub(_email, text)
    if secret_hits or email_redactions:
        warnings.append("sensitive_content_redacted")

    if len(text) > MAX_REPLY_CHARS:
        text = text[:MAX_REPLY_CHARS].rstrip() + "…"
        warnings.append("truncated")
    if not text:
        response_type = "cannot_verify"
        text = "I'm sorry — I couldn't produce a reliable answer. Please contact support@cloudbox.example."
        warnings.append("empty_reply")

    return ValidatedOutput(
        response_type=response_type if response_type in RESPONSE_TYPES else "answer",
        text=text,
        cited_ids=cited,
        invalid_citations=invalid,
        warnings=warnings,
        redactions=secret_hits + email_redactions,
    )
