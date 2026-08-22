"""Error monitoring endpoints for Sentry integration and error tracking."""

import json
import os
from datetime import datetime, timedelta
from typing import Optional

import sentry_sdk
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel


router = APIRouter(prefix="/api/errors", tags=["error-monitoring"])


class ErrorEvent(BaseModel):
    """Schema for error event response."""
    error_id: str
    timestamp: str
    level: str
    message: str
    exception_type: Optional[str] = None
    request_id: Optional[str] = None
    context: dict = {}


class ErrorStats(BaseModel):
    """Schema for error statistics."""
    total_errors: int
    critical_errors: int
    warnings: int
    time_period_minutes: int
    top_error_types: list


class ErrorTestPayload(BaseModel):
    """Schema for testing error capture."""
    error_type: str = "test_error"
    message: str = "Test error from error monitoring endpoint"
    should_raise: bool = True


def get_error_log_file() -> Optional[str]:
    """Get the path to the error log file."""
    log_dir = os.getenv("LOG_DIR", "logs")
    error_log = os.path.join(log_dir, "error.log")
    if os.path.exists(error_log):
        return error_log
    return None


def read_recent_errors(limit: int = 50, minutes: int = 60) -> list:
    """Read recent errors from the error log file."""
    error_log = get_error_log_file()
    if not error_log:
        return []

    errors = []
    cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)

    try:
        with open(error_log, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("level") == "ERROR":
                        timestamp_str = entry.get("timestamp", "")
                        try:
                            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                            if timestamp >= cutoff_time:
                                errors.append(entry)
                        except (ValueError, AttributeError):
                            pass
                except json.JSONDecodeError:
                    continue

        # Return most recent errors first
        return sorted(errors, key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]
    except IOError:
        return []


def calculate_error_stats(minutes: int = 60) -> dict:
    """Calculate error statistics for the given time period."""
    errors = read_recent_errors(limit=1000, minutes=minutes)

    stats = {
        "total_errors": len(errors),
        "critical_errors": 0,
        "warnings": 0,
        "time_period_minutes": minutes,
        "top_error_types": [],
    }

    error_type_counts = {}

    for error in errors:
        level = error.get("level", "ERROR")
        if level == "CRITICAL":
            stats["critical_errors"] += 1
        elif level == "WARNING":
            stats["warnings"] += 1

        # Track error types
        exc_type = error.get("exc_info", {}).get("exc_type")
        if exc_type:
            error_type_counts[exc_type] = error_type_counts.get(exc_type, 0) + 1

    # Get top 5 error types
    top_errors = sorted(error_type_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    stats["top_error_types"] = [{"type": name, "count": count} for name, count in top_errors]

    return stats


@router.get("/", response_model=list[ErrorEvent])
async def get_recent_errors(
    limit: int = Query(50, ge=1, le=500),
    minutes: int = Query(60, ge=1, le=1440),
) -> list[ErrorEvent]:
    """
    Get recent error events from the system.

    - **limit**: Maximum number of errors to return (1-500)
    - **minutes**: Look back time period in minutes (1-1440)
    """
    errors = read_recent_errors(limit=limit, minutes=minutes)

    result = []
    for error in errors:
        result.append(
            ErrorEvent(
                error_id=error.get("error_id", "unknown"),
                timestamp=error.get("timestamp", ""),
                level=error.get("level", "ERROR"),
                message=error.get("message", ""),
                exception_type=error.get("exc_info", {}).get("exc_type"),
                request_id=error.get("request_id"),
                context=error.get("context", {}),
            )
        )

    return result


@router.get("/{error_id}", response_model=dict)
async def get_error_details(error_id: str) -> dict:
    """
    Get detailed information about a specific error.

    Error ID can be obtained from the recent errors endpoint or from Sentry.
    """
    error_log = get_error_log_file()
    if not error_log:
        raise HTTPException(status_code=404, detail="Error not found")

    try:
        with open(error_log, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("error_id") == error_id or entry.get("sentry_id") == error_id:
                        return entry
                except json.JSONDecodeError:
                    continue
    except IOError:
        pass

    raise HTTPException(status_code=404, detail="Error not found")


@router.get("/stats", response_model=ErrorStats)
async def get_error_statistics(
    minutes: int = Query(60, ge=1, le=1440),
) -> ErrorStats:
    """
    Get error statistics for the specified time period.

    - **minutes**: Time period in minutes (1-1440)
    """
    stats = calculate_error_stats(minutes=minutes)
    return ErrorStats(**stats)


@router.post("/test", response_model=dict)
async def test_error_capture(payload: ErrorTestPayload) -> dict:
    """
    Test error capture and Sentry integration.

    This endpoint simulates error conditions to verify that error tracking
    is working correctly. Use for testing and validation only.

    - **error_type**: Type of error to simulate (test_error, value_error, runtime_error)
    - **message**: Custom error message
    - **should_raise**: Whether to raise the error (True) or just capture (False)
    """
    with sentry_sdk.push_scope() as scope:
        scope.set_context("test_error", {
            "type": payload.error_type,
            "message": payload.message,
            "timestamp": datetime.utcnow().isoformat(),
        })
        scope.set_tag("test_execution", "true")
        scope.set_level("warning")

        sentry_sdk.capture_message(f"Test error: {payload.message}")

        if payload.should_raise:
            if payload.error_type == "value_error":
                raise ValueError(payload.message)
            elif payload.error_type == "runtime_error":
                raise RuntimeError(payload.message)
            else:
                raise Exception(payload.message)

        return {
            "status": "captured",
            "error_type": payload.error_type,
            "message": payload.message,
        }


@router.get("/sentry/health", response_model=dict)
async def sentry_health() -> dict:
    """
    Check Sentry integration health and configuration status.

    Returns information about Sentry DSN, environment, and connection status.
    """
    dsn = os.getenv("SENTRY_DSN")
    environment = os.getenv("SENTRY_ENVIRONMENT", "development")

    if not dsn or dsn.startswith("https://key@"):
        return {
            "status": "disabled",
            "reason": "SENTRY_DSN not configured",
            "environment": environment,
        }

    hub = sentry_sdk.Hub.current
    client = hub.client

    return {
        "status": "enabled",
        "environment": environment,
        "dsn_configured": True,
        "release": os.getenv("SENTRY_RELEASE", "unknown"),
        "sample_rate": float(os.getenv("SENTRY_SAMPLE_RATE", "1.0")),
        "traces_sample_rate": float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        "integrations": [
            "FastApiIntegration",
            "HttpxIntegration",
            "AsyncioIntegration",
            "LoggingIntegration",
        ],
    }
