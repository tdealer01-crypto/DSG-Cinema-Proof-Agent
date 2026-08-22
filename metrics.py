"""Metrics and health endpoints for DSG Cinema.

Read surfaces report observed process/verifier state. Metric mutation is an
admin-only operation so external callers cannot fabricate dashboard evidence.
"""

from __future__ import annotations

import hmac
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import psutil
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from logging_config import logger

router = APIRouter(prefix="/api", tags=["metrics"])
_STARTED_MONOTONIC = time.monotonic()


class HealthCheckResponse(BaseModel):
    status: str
    timestamp: str
    uptime: float
    checks: dict[str, str]
    memory: dict[str, Any]
    cpu: dict[str, Any]


class MetricData(BaseModel):
    id: str
    label: str
    value: float
    target: float
    status: str
    description: str
    actionUrl: str | None = None


class MetricsResponse(BaseModel):
    metrics: list[MetricData]
    overallHealth: float
    criticalIssues: int
    lastSync: str


_metrics_state = {
    "verification_requests": 0,
    "verification_successes": 0,
    "verification_failures": 0,
    "z3_solver_failures": 0,
    "average_solve_time_ms": 0.0,
    "errors_last_24h": 0,
}


def update_metric(metric_name: str, value: float | int) -> None:
    if metric_name not in _metrics_state:
        raise KeyError(metric_name)
    _metrics_state[metric_name] = value
    logger.debug("Metric updated", extra={"extra_data": {"metric": metric_name, "value": value}})


def increment_metric(metric_name: str, delta: float = 1) -> None:
    if metric_name not in _metrics_state:
        raise KeyError(metric_name)
    _metrics_state[metric_name] += delta


def _require_metrics_admin(authorization: Optional[str]) -> None:
    expected = (os.getenv("CINEMA_API_SECRET") or "").strip()
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail="metrics admin authentication is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="invalid admin token")


async def _z3_health() -> str:
    """Probe the same exact verifier used by Cinema; never hard-code readiness."""
    try:
        import cinema_main

        status_code, body = await cinema_main.z3_request("GET", "/ready")
        if status_code == 200 and isinstance(body, dict) and body.get("status") == "ready":
            return "ok"
        return "error"
    except Exception as exc:
        logger.warning("Z3 health probe failed", extra={"extra_data": {"error_type": type(exc).__name__}})
        return "error"


@router.get("/health", response_model=HealthCheckResponse)
async def health_check(request: Request) -> HealthCheckResponse:
    try:
        process = psutil.Process()
        mem_info = process.memory_info()
        memory_percent = process.memory_percent()
        cpu_percent = process.cpu_percent(interval=0.1)
        system_memory = psutil.virtual_memory()
        z3_status = await _z3_health()

        checks = {
            "memory": "ok" if memory_percent < 80 else "warning",
            "cpu": "ok" if cpu_percent < 90 else "warning",
            "z3_backend": z3_status,
        }

        status = "healthy"
        if any(v == "warning" for v in checks.values()):
            status = "degraded"
        if any(v == "error" for v in checks.values()):
            status = "unhealthy"

        return HealthCheckResponse(
            status=status,
            timestamp=datetime.now(timezone.utc).isoformat(),
            uptime=max(0.0, time.monotonic() - _STARTED_MONOTONIC),
            checks=checks,
            memory={
                "process_rss_mb": mem_info.rss / 1024 / 1024,
                "process_vms_mb": mem_info.vms / 1024 / 1024,
                "process_percent": memory_percent,
                "system_available_mb": system_memory.available / 1024 / 1024,
                "system_percent": system_memory.percent,
            },
            cpu={
                "percent": cpu_percent,
                "num_threads": process.num_threads(),
            },
        )
    except Exception as exc:
        logger.error("Health check failed", exc_info=exc)
        return HealthCheckResponse(
            status="unhealthy",
            timestamp=datetime.now(timezone.utc).isoformat(),
            uptime=max(0.0, time.monotonic() - _STARTED_MONOTONIC),
            checks={"error": "failed to check"},
            memory={},
            cpu={},
        )


@router.get("/metrics/critical", response_model=MetricsResponse)
async def critical_metrics(request: Request) -> MetricsResponse:
    try:
        total_requests = _metrics_state["verification_requests"]
        successes = _metrics_state["verification_successes"]
        success_rate = (successes / total_requests * 100) if total_requests > 0 else 0.0

        z3_health = 100 - (
            _metrics_state["z3_solver_failures"] / max(total_requests, 1) * 100
        )
        solve_score = 100 - min(_metrics_state["average_solve_time_ms"] / 10, 100)
        error_health = 100 - min(
            _metrics_state["errors_last_24h"] / max(total_requests / 1000, 1), 100
        )

        metrics = [
            MetricData(
                id="verification-success-rate",
                label="Verification Success Rate",
                value=success_rate,
                target=99.5,
                status="success" if total_requests > 0 and success_rate >= 95 else "warning",
                description=(
                    f"{success_rate:.1f}% of {total_requests} observed verifications successful"
                    if total_requests > 0
                    else "No verification observations recorded in this process"
                ),
                actionUrl="/dashboard/verifications",
            ),
            MetricData(
                id="z3-solver-health",
                label="Z3 Solver Health",
                value=z3_health,
                target=100,
                status="success" if _metrics_state["z3_solver_failures"] == 0 else "danger",
                description=f"{_metrics_state['z3_solver_failures']} observed solver failures",
                actionUrl="/dashboard/solver",
            ),
            MetricData(
                id="average-solve-time",
                label="Average Solve Time",
                value=solve_score,
                target=95,
                status="success" if _metrics_state["average_solve_time_ms"] < 100 else "warning",
                description=f"{_metrics_state['average_solve_time_ms']:.1f}ms observed average",
                actionUrl="/dashboard/performance",
            ),
            MetricData(
                id="error-rate",
                label="Error Rate (24h)",
                value=error_health,
                target=99.9,
                status="success" if _metrics_state["errors_last_24h"] < 10 else "warning",
                description=f"{_metrics_state['errors_last_24h']} observed errors in 24h",
                actionUrl="/dashboard/errors",
            ),
        ]

        overall_health = sum(m.value for m in metrics) / len(metrics) if metrics else 0
        critical_issues = sum(1 for m in metrics if m.status == "danger")

        return MetricsResponse(
            metrics=metrics,
            overallHealth=overall_health,
            criticalIssues=critical_issues,
            lastSync=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        logger.error("Failed to compute metrics", exc_info=exc)
        return MetricsResponse(
            metrics=[],
            overallHealth=0,
            criticalIssues=1,
            lastSync=datetime.now(timezone.utc).isoformat(),
        )


@router.post("/metrics/custom")
async def record_custom_metric(
    request: Request,
    metric_name: str,
    value: float,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """Record a known metric through an authenticated server/admin path only."""
    _require_metrics_admin(authorization)
    if metric_name not in _metrics_state:
        raise HTTPException(status_code=404, detail="unknown metric")
    update_metric(metric_name, value)
    return {"success": True, "metric": metric_name, "value": value}


__all__ = ["router", "update_metric", "increment_metric"]
