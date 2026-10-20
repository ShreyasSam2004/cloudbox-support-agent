"""Context management: what the model sees from the conversation.

* Only the last ``max_turns`` user/assistant turns are sent verbatim; older turns are reduced to a
  one-line summary each (no extra model call).
* Prior assistant answers are truncated; prior tool calls and retrieved passages are **never**
  replayed — the agent re-retrieves when it needs evidence, so stale or untrusted content does not
  accumulate in the context.
* Durable facts (customer IDs, previous account lookups) live in session state and are rendered into
  the trusted session-context block instead.
"""

from __future__ import annotations

from backend.models.base import ChatMessage
from backend.storage.sessions import Session, Turn


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ContextBuilder:
    def __init__(self, max_turns: int = 6, max_assistant_chars: int = 1500, summary_chars: int = 140) -> None:
        self.max_turns = max_turns
        self.max_assistant_chars = max_assistant_chars
        self.summary_chars = summary_chars

    def history(self, session: Session) -> list[Turn]:
        """Turns before the current user message (the handler appends the current message first)."""
        turns = session.turns
        if turns and turns[-1].role == "user":
            turns = turns[:-1]
        return turns

    def build(self, session: Session, user_message: str) -> tuple[list[ChatMessage], str | None]:
        turns = self.history(session)
        recent = turns[-self.max_turns :] if self.max_turns > 0 else []
        older = turns[: len(turns) - len(recent)]

        summary: str | None = None
        if older:
            parts = []
            for turn in older:
                if turn.role == "user":
                    parts.append(f'customer asked "{_shorten(turn.content, self.summary_chars)}"')
                else:
                    sources = f"; sources: {', '.join(turn.source_titles[:3])}" if turn.source_titles else ""
                    parts.append(f"you replied ({turn.response_type or 'answer'}{sources})")
            summary = "; ".join(parts)

        messages: list[ChatMessage] = []
        for turn in recent:
            if turn.role == "user":
                messages.append(ChatMessage.user(turn.content))
            else:
                messages.append(ChatMessage.assistant(_shorten(turn.content, self.max_assistant_chars)))
        # Providers require the conversation to start with a user turn.
        while messages and messages[0].role != "user":
            messages.pop(0)
        messages.append(ChatMessage.user(user_message))
        return messages, summary
