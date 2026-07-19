"""
Structured Logging & Request ID Tracking

Provides JSON-formatted logging with standard fields per SAD §13 and Project Rules §9:
- request_id: unique per request
- trace_id: for distributed tracing (reserved)
- latency_ms: request duration
- tool_name: MCP tool used (if applicable)
- cost: LLM cost (if applicable)

Architecture rules:
- No sensitive data in logs (no prompts, no raw LLM outputs)
- 30-day retention (DEPLOYMENT.md §18)
"""

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

# Context variables for request-scoped data
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(""),
            "trace_id": trace_id_var.get(""),
        }

        # Add extra fields if present
        if hasattr(record, "extra_data"):
            log_entry.update(record.extra_data)

        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure structured JSON logging for the application."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter(datefmt="%Y-%m-%dT%H:%M:%S"))

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())


def set_request_context(request_id: str, trace_id: str = "") -> None:
    """Set request-scoped context variables."""
    request_id_var.set(request_id)
    trace_id_var.set(trace_id or request_id)


def clear_request_context() -> None:
    """Clear request-scoped context variables."""
    request_id_var.set("")
    trace_id_var.set("")


class RequestTimer:
    """Context manager to measure request latency."""

    def __init__(self):
        self.start_time: float = 0
        self.latency_ms: float = 0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.latency_ms = round((time.perf_counter() - self.start_time) * 1000, 2)
