"""Structured logging.

JSON key/value only, never string concatenation. Every line carries
``timestamp``, ``level``, ``service`` and, where one exists, ``trace_id``.
Secrets and full PII never reach a log line — see ``_scrub``.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

# What a structlog processor is handed and must hand back.
EventDict = MutableMapping[str, Any]

trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "authorization",
        "password",
        "secret",
        "master_key",
        "data_key",
        "ciphertext",
        "client_secret",
        "email",
    }
)


def _scrub(_logger: Any, _name: str, event: EventDict) -> EventDict:
    for key in list(event):
        if key.lower() in _SENSITIVE_KEYS:
            event[key] = "[redacted]"
    return event


def _add_trace_id(_logger: Any, _name: str, event: EventDict) -> EventDict:
    trace_id = trace_id_var.get()
    if trace_id is not None:
        event["trace_id"] = trace_id
    return event


def configure_logging(service: str, level: str) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            _add_trace_id,
            _scrub,
            structlog.processors.EventRenamer("message"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
