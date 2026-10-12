"""
Structured logging for MUTAGEN.

Uses Python's standard logging with structured messages.
Supports correlation IDs for experiment tracing.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Optional

# Context variable for correlation/experiment IDs
_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def set_correlation_id(cid: str) -> None:
    """Set the current correlation ID for log context."""
    _correlation_id.set(cid)


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID."""
    return _correlation_id.get()


class CorrelationFilter(logging.Filter):
    """Inject correlation ID into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or "-"  # type: ignore[attr-defined]
        return True


def setup_logging(level: str = "INFO", stream: object = None) -> logging.Logger:
    """
    Configure the MUTAGEN root logger.

    Args:
        level: Logging level name.
        stream: Output stream (defaults to stderr to keep stdout clean for JSON).

    Returns:
        Configured root logger.
    """
    if stream is None:
        stream = sys.stderr

    logger = logging.getLogger("mutagen")

    # Avoid duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(stream)  # type: ignore[arg-type]
    handler.setLevel(logger.level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(correlation_id)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationFilter())

    logger.addHandler(handler)
    logger.propagate = False

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the mutagen namespace."""
    return logging.getLogger(f"mutagen.{name}")
