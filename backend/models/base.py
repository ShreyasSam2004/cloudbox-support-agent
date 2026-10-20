"""Provider-neutral LLM interface.

The agent, the retrieval evaluator, the baseline and the judge all talk to models exclusively
through :class:`LLMProvider`. Concrete providers translate this neutral format to and from their
native APIs (Anthropic Messages, OpenAI Chat Completions, Ollama /api/chat).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- content blocks


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolCall(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


ContentBlock = Annotated[TextBlock | ToolCall | ToolResultBlock, Field(discriminator="type")]


class ChatMessage(BaseModel):
    """One conversation message.

    ``role="system"`` inside ``messages`` is a *mid-conversation operator notice* (e.g. "step
    budget exhausted"). Providers that do not support it natively fold it into a user turn.

    ``provider_raw`` holds the provider-native assistant content (e.g. Anthropic thinking blocks)
    so the same provider can replay it byte-for-byte within an agent loop.
    """

    role: Literal["user", "assistant", "system"]
    content: list[ContentBlock]
    provider_raw: list[dict[str, Any]] | None = None
    provider_name: str | None = None

    @classmethod
    def user(cls, text: str) -> ChatMessage:
        return cls(role="user", content=[TextBlock(text=text)])

    @classmethod
    def assistant(cls, text: str) -> ChatMessage:
        return cls(role="assistant", content=[TextBlock(text=text)])

    @classmethod
    def system_notice(cls, text: str) -> ChatMessage:
        return cls(role="system", content=[TextBlock(text=text)])

    @classmethod
    def tool_results(cls, results: list[ToolResultBlock]) -> ChatMessage:
        return cls(role="user", content=list(results))

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.content if isinstance(b, TextBlock))

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [b for b in self.content if isinstance(b, ToolCall)]


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


Purpose = Literal["agent", "evaluator", "baseline", "judge"]


class LLMRequest(BaseModel):
    system: str
    """Static system prompt (identical across requests → prompt-cacheable)."""
    system_dynamic: str | None = None
    """Per-request context rendered after the cache breakpoint (date, session facts)."""
    messages: list[ChatMessage]
    tools: list[ToolSpec] = Field(default_factory=list)
    tool_choice: Literal["auto", "none"] = "auto"
    max_output_tokens: int = 4096
    response_schema: dict[str, Any] | None = None
    """When set, the provider must return a single JSON object matching this schema as text."""
    effort: str | None = None
    purpose: Purpose = "agent"


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens


StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"]


class LLMResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: StopReason = "end_turn"
    usage: Usage = Field(default_factory=Usage)
    model: str
    provider: str
    latency_ms: float = 0.0
    raw_assistant_content: list[dict[str, Any]] | None = None

    def to_assistant_message(self) -> ChatMessage:
        blocks: list[ContentBlock] = []
        if self.text:
            blocks.append(TextBlock(text=self.text))
        blocks.extend(self.tool_calls)
        if not blocks:
            blocks.append(TextBlock(text=""))
        return ChatMessage(
            role="assistant",
            content=blocks,
            provider_raw=self.raw_assistant_content,
            provider_name=self.provider,
        )


# --------------------------------------------------------------------------- errors


class LLMError(Exception):
    """Provider failure. ``retryable`` distinguishes transient from permanent errors."""

    def __init__(self, message: str, *, retryable: bool, provider: str, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.provider = provider
        self.status_code = status_code


# --------------------------------------------------------------------------- protocol


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    async def aclose(self) -> None: ...
