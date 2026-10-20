"""Application metrics.

Instruments are Prometheus objects (scraped at ``/metrics`` locally). In Azure, the same signals reach
Application Insights through OpenTelemetry (see :mod:`backend.observability.telemetry`): request
traces and dependency calls are auto-instrumented, and every agent run also emits one structured
``agent.completed`` log record that Log Analytics queries and alerts are built on.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

AGENT_RUNS = Counter("cloudbox_agent_runs_total", "Agent executions", ["stop_reason", "response_type"])
AGENT_STEPS = Histogram(
    "cloudbox_agent_steps", "LLM steps per agent execution", buckets=(1, 2, 3, 4, 5, 6, 8, 10, 15, 25)
)
AGENT_LATENCY = Histogram(
    "cloudbox_agent_latency_seconds",
    "End-to-end agent latency",
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)
TOOL_CALLS = Counter("cloudbox_tool_calls_total", "Tool executions", ["tool", "status"])
TOOL_LATENCY = Histogram(
    "cloudbox_tool_latency_seconds", "Tool latency", ["tool"], buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30)
)
LLM_CALLS = Counter("cloudbox_llm_calls_total", "LLM calls", ["provider", "model", "purpose", "status"])
LLM_LATENCY = Histogram(
    "cloudbox_llm_latency_seconds",
    "LLM call latency",
    ["provider", "purpose"],
    buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 40, 80, 160),
)
LLM_TOKENS = Counter("cloudbox_llm_tokens_total", "LLM tokens", ["model", "purpose", "kind"])
LLM_COST = Counter("cloudbox_llm_cost_usd_total", "Estimated LLM cost (USD)", ["model", "purpose"])
RETRIEVAL_VERDICTS = Counter("cloudbox_retrieval_verdicts_total", "Retrieval evaluator verdicts", ["verdict"])
RETRIEVAL_ATTEMPTS = Histogram(
    "cloudbox_retrieval_attempts", "KB searches per execution", buckets=(0, 1, 2, 3, 4, 5, 8)
)
GUARDRAIL_EVENTS = Counter("cloudbox_guardrail_events_total", "Guardrail interventions", ["kind"])
RATE_LIMITED = Counter("cloudbox_rate_limited_total", "Requests rejected by the rate limiter")
