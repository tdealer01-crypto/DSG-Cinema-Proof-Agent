"""Enhanced Sentry configuration with performance monitoring and custom integrations."""

import os
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.tracing import Transaction


def initialize_sentry_advanced():
    """Initialize Sentry with advanced configuration including performance monitoring."""
    dsn = os.getenv("SENTRY_DSN")
    environment = os.getenv("SENTRY_ENVIRONMENT", "development")
    release = os.getenv("SENTRY_RELEASE", "unknown")
    sample_rate = float(os.getenv("SENTRY_SAMPLE_RATE", "1.0"))
    traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))

    if not dsn or dsn.startswith("https://key@"):
        return None

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        sample_rate=sample_rate,
        traces_sample_rate=traces_sample_rate,
        integrations=[
            FastApiIntegration(),
            HttpxIntegration(),
            AsyncioIntegration(),
            LoggingIntegration(
                level=os.getenv("LOG_LEVEL", "info").upper(),
                event_level="error"
            ),
        ],
        before_send=filter_errors,
        before_send_transaction=filter_transactions,
        attach_stacktrace=True,
        send_default_pii=False,
        max_breadcrumbs=50,
    )
    return sentry_sdk.Hub.current


def filter_errors(event, hint):
    """Filter errors to exclude noise and sensitive data."""
    # Ignore common non-critical errors
    if hint.get("exc_info"):
        exc_type = hint["exc_info"][0]
        if exc_type.__name__ in ("ConnectionError", "TimeoutError"):
            if "test" in str(hint.get("exc_info", [""])[1]).lower():
                return None

    # Remove sensitive data from error messages
    if event.get("exception"):
        for exception in event["exception"]["values"]:
            if exception.get("value"):
                exception["value"] = sanitize_error_message(exception["value"])

    return event


def filter_transactions(event, hint):
    """Filter transactions to reduce noise from health checks and metrics."""
    request = event.get("request", {})
    path = request.get("url", "")

    # Skip health check transactions
    if any(skip in path for skip in ["/health", "/metrics", "/ready"]):
        return None

    # Sample verbose endpoints
    if "/verify" in path:
        import random
        if random.random() > 0.5:  # Keep only 50% of verification transactions
            return None

    return event


def sanitize_error_message(message: str) -> str:
    """Remove sensitive data from error messages."""
    import re
    # Remove API keys
    message = re.sub(r"sk_live_\w+", "sk_live_***", message)
    message = re.sub(r"rk_live_\w+", "rk_live_***", message)
    message = re.sub(r"dsg_\w+_[0-9a-f]+", "dsg_***", message)
    return message


def capture_cinema_error(error_type: str, details: dict, level: str = "error"):
    """Capture Cinema-specific errors with context."""
    with sentry_sdk.push_scope() as scope:
        scope.set_context("cinema", {
            "error_type": error_type,
            "details": details,
        })
        scope.set_level(level)
        sentry_sdk.capture_message(f"Cinema Error: {error_type}")


def capture_z3_performance(solver_name: str, duration_ms: float, result: str):
    """Capture Z3 solver performance metrics."""
    with sentry_sdk.push_scope() as scope:
        scope.set_context("z3_performance", {
            "solver": solver_name,
            "duration_ms": duration_ms,
            "result": result,
        })
        scope.set_tag("performance_category", "slow" if duration_ms > 500 else "fast")
        if duration_ms > 500:
            sentry_sdk.capture_message(f"Z3 Slow: {solver_name} took {duration_ms}ms")


def capture_verification_flow(channel: str, execution_id: str, decision: str, duration_ms: float):
    """Capture complete verification flow metrics."""
    with sentry_sdk.push_scope() as scope:
        scope.set_context("verification_flow", {
            "channel": channel,
            "execution_id": execution_id,
            "decision": decision,
            "duration_ms": duration_ms,
        })
        scope.set_tag("decision", decision)
        scope.set_tag("channel", channel)


class SentryPerformanceTracker:
    """Context manager for tracking operation performance with Sentry."""

    def __init__(self, operation_name: str, critical_threshold_ms: int = 500):
        self.operation_name = operation_name
        self.critical_threshold_ms = critical_threshold_ms
        self.transaction = None
        self.start_time = None

    def __enter__(self):
        import time
        self.start_time = time.time()
        self.transaction = sentry_sdk.start_transaction(
            op=self.operation_name,
            name=self.operation_name,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import time
        if self.transaction:
            self.transaction.finish()

        duration_ms = (time.time() - self.start_time) * 1000

        if duration_ms > self.critical_threshold_ms:
            with sentry_sdk.push_scope() as scope:
                scope.set_context("slow_operation", {
                    "operation": self.operation_name,
                    "duration_ms": duration_ms,
                    "threshold_ms": self.critical_threshold_ms,
                })
                scope.set_level("warning")
                sentry_sdk.capture_message(
                    f"Slow operation: {self.operation_name} took {duration_ms:.1f}ms"
                )


# Initialize on import if SENTRY_DSN is set
if os.getenv("SENTRY_DSN"):
    initialize_sentry_advanced()
