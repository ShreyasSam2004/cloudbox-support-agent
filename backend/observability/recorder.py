"""Per-execution recording via contextvars.

The agent loop opens a recording scope; anything that runs inside it — the agent's own model
calls, the retrieval evaluator's model calls inside a tool, tool executions — appends to the same
:class:`AgentTrace` without having the trace threaded through every function signature.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from backend.schemas.trace import AgentTrace, LLMCallRecord


@dataclass
class ExecutionRecorder:
    trace: AgentTrace
    step: int = 0

    def add_llm_call(self, record: LLMCallRecord) -> None:
        self.trace.llm_calls.append(record)


_current: ContextVar[ExecutionRecorder | None] = ContextVar("cloudbox_execution_recorder", default=None)


def current_recorder() -> ExecutionRecorder | None:
    return _current.get()


@contextmanager
def recording(recorder: ExecutionRecorder) -> Iterator[ExecutionRecorder]:
    token = _current.set(recorder)
    try:
        yield recorder
    finally:
        _current.reset(token)
