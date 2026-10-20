"""Structured JSON logging with request/session/execution correlation IDs.

IDs are bound with :func:`bind_context` (contextvars), so every log line emitted while handling a
request carries them automatically — including lines from tools and providers.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_SENSITIVE_KEYS = {"api_key", "authorization", "password", "secret", "token", "contact_email", "email"}


def _redact(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event):
        if key.lower() in _SENSITIVE_KEYS:
            event[key] = "[REDACTED]"
    return event


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper(), force=True)
    for noisy in ("httpx", "httpcore", "httpx2", "anthropic", "openai", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    renderer: Any = structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


def bind_context(**values: Any) -> None:
    structlog.contextvars.bind_contextvars(**{k: v for k, v in values.items() if v is not None})


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()
