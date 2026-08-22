"""Production-grade logging configuration for DSG Cinema.

Provides structured logging with file rotation, JSON formatting, and error tracking.
Integrates with Sentry for exception reporting in production.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Create logs directory
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
NODE_ENV = os.getenv("NODE_ENV", os.getenv("ENV", "development")).lower()


class StructuredFormatter(logging.Formatter):
    """Format logs as JSON for easier parsing and analysis."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id

        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id

        if hasattr(record, "extra_data"):
            log_data["data"] = record.extra_data

        return json.dumps(log_data)


def get_logger(name: str) -> logging.Logger:
    """Get or create a logger with structured formatting."""
    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVEL)

    if logger.handlers:
        return logger

    formatter = StructuredFormatter()

    # File handler for all logs (with rotation)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "combined.log",
        maxBytes=52_428_800,  # 50MB
        backupCount=10,
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    # File handler for errors only
    error_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "error.log",
        maxBytes=10_485_760,  # 10MB
        backupCount=5,
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)
    logger.addHandler(error_handler)

    # Console handler for development
    if NODE_ENV != "production":
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(LOG_LEVEL)
        logger.addHandler(console_handler)

    return logger


def initialize_sentry() -> None:
    """Initialize Sentry for error tracking in production."""
    if not SENTRY_DSN:
        logger = get_logger(__name__)
        logger.warning("SENTRY_DSN not configured, error tracking disabled")
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.httpx import HttpxIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            environment=NODE_ENV,
            traces_sample_rate=0.1,
            integrations=[
                FastApiIntegration(),
                HttpxIntegration(),
            ],
        )

        logger = get_logger(__name__)
        logger.info("Sentry initialized", extra={"env": NODE_ENV})
    except ImportError:
        logger = get_logger(__name__)
        logger.warning("sentry-sdk not installed, error tracking unavailable")


def generate_request_id() -> str:
    """Generate a unique request ID for tracing."""
    return str(uuid.uuid4())


class LogContext:
    """Context manager for adding request context to logs."""

    def __init__(self, logger: logging.Logger, request_id: str, **kwargs: Any):
        self.logger = logger
        self.request_id = request_id
        self.extra = kwargs

    def __enter__(self) -> LogContext:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type:
            self.logger.error(
                f"Exception in request {self.request_id}",
                exc_info=(exc_type, exc_val, exc_tb),
                extra={"request_id": self.request_id, **self.extra},
            )

    def log_metric(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """Log a metric with optional tags."""
        data = {"metric": name, "value": value}
        if tags:
            data["tags"] = tags
        self.logger.info(
            f"Metric: {name}",
            extra={"request_id": self.request_id, "extra_data": data},
        )

    def log_event(self, event: str, **kwargs: Any) -> None:
        """Log a business event."""
        self.logger.info(
            event,
            extra={"request_id": self.request_id, "extra_data": kwargs},
        )


# Main logger instance
logger = get_logger("cinema")

__all__ = [
    "get_logger",
    "logger",
    "initialize_sentry",
    "generate_request_id",
    "LogContext",
    "LOG_DIR",
]
