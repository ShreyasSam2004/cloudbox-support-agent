"""Tool abstractions.

A tool is a typed capability: a Pydantic input model (→ JSON schema for the LLM), a description
written for the model, and an async ``run``. Tools never raise into the agent loop — the registry
turns every failure into an observation the model can reason about.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, model_validator

from backend.config.settings import Settings
from backend.models.base import ToolSpec
from backend.schemas.domain import RetrievalVerdict
from backend.schemas.trace import ActivityEvent
from backend.security.auth import Principal
from backend.storage.sessions import Session
from backend.tools.evidence import EvidenceLedger

EventSink = Callable[[ActivityEvent], Awaitable[None]]


class ToolError(Exception):
    """Expected tool failure, surfaced to the model as an error observation."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class ToolInput(BaseModel):
    """Base for tool inputs. Lenient with the quirks of real model output (``""``/``"null"`` → None)."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def _null_strings(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {
                k: (None if isinstance(v, str) and v.strip().lower() in ("", "null", "none") else v)
                for k, v in data.items()
            }
        return data


@dataclass
class ToolBudget:
    max_calls: int
    used: int = 0

    @property
    def exhausted(self) -> bool:
        return self.used >= self.max_calls


@dataclass
class ToolContext:
    execution_id: str
    session: Session
    principal: Principal
    user_message: str
    ledger: EvidenceLedger
    settings: Settings
    now: datetime
    budget: ToolBudget
    emit: EventSink | None = None
    extras: dict[str, Any] = field(default_factory=dict)


class ToolOutput(BaseModel):
    observation: dict[str, Any]
    summary: str
    evidence_ids: list[str] = []
    verdict: RetrievalVerdict | None = None


def _clean_schema(schema: Any) -> Any:
    """Drop Pydantic noise (titles) that wastes tokens in every request."""
    if isinstance(schema, dict):
        return {k: _clean_schema(v) for k, v in schema.items() if k != "title"}
    if isinstance(schema, list):
        return [_clean_schema(v) for v in schema]
    return schema


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[ToolInput]]
    activity_label: ClassVar[str]
    timeout_s: float | None = None

    def spec(self) -> ToolSpec:
        schema = self.input_model.model_json_schema()
        cleaned: dict[str, Any] = {
            "type": "object",
            "properties": {k: _clean_schema(v) for k, v in schema.get("properties", {}).items()},
            "required": schema.get("required", []),
        }
        return ToolSpec(name=self.name, description=self.description, input_schema=cleaned)

    @abstractmethod
    async def run(self, args: Any, ctx: ToolContext) -> ToolOutput: ...
