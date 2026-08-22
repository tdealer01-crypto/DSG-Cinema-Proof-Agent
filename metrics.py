"""Metrics and health check endpoints for DSG Cinema."""

from __future__ import annotations

import psutil
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from logging_config import logger

router = APIRouter(prefix="/api", tags=["metrics"])


class HealthCheckResponse(BaseModel):
    """Health check response model."""

    status: str  # 'healthy', 'degraded', 'unhealthy'
    timestamp: str
    uptime: float
    checks: dict[str, str]
    memory: dict[str, Any]
    cpu: dict[str, Any]


class MetricData(BaseModel):
    """Single metric data point."""

    id: str
    label: str
    value: float
    target: float
    status: str  # 'success', 'warning', 'danger'
    description: str
    actionUrl: str | None = None


class MetricsResponse(BaseModel):
    """Critical metrics response model."""

    metrics: list[MetricData]
    overallHealth: float
    criticalIssues: int
    lastSync: str


# In-memory metrics storage (can be replaced with Redis/database)
_metrics_state = {
    "verification_requests": 0,
    "verification_successes": 0,
    "verification_failures": 0,
    "z3_solver_failures": 0,
    "average_solve_time_ms": 0.0,
    "errors_last_24h": 0,
}


def update_metric(metric_name: str, value: float | int) -> None:
    """Update a metric value."""
    if metric_name in _metrics_state:
        _metrics_state[metric_name] = value
        logger.debug(f"Metric updated: {metric_name}={value}")


def increment_metric(metric_name: str, delta: float = 1) -> None:
    """Increment a metric value."""
    if metric_name in _metrics_state:
        _metrics_state[metric_name] += delta


@router.get("/health", response_model=HealthCheckResponse)
async def health_check(request: Request) -> HealthCheckResponse:
    """Health check endpoint with system status."""
    try:
        # Get memory usage
        process = psutil.Process()
        mem_info = process.memory_info()
        memory_percent = process.memory_percent()

        # Get CPU usage
        cpu_percent = process.cpu_percent(interval=0.1)

        # Get system memory
        system_memory = psutil.virtual_memory()

        # Determine overall status
        checks = {
            "memory": "ok" if memory_percent < 80 else "warning",
            "cpu": "ok" if cpu_percent < 90 else "warning",
            "z3_backend": "ok",  # Would check actual connectivity
        }

        status = "healthy"
        if any(v == "warning" for v in checks.values()):
            status = "degraded"
        if any(v == "error" for v in checks.values()):
            status = "unhealthy"

        return HealthCheckResponse(
            status=status,
            timestamp=datetime.now(timezone.utc).isoformat(),
            uptime=process.create_time(),
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
            uptime=0,
            checks={"error": "failed to check"},
            memory={},
            cpu={},
        )


@router.get("/metrics/critical", response_model=MetricsResponse)
async def critical_metrics(request: Request) -> MetricsResponse:
    """Get critical system metrics for the dashboard."""
    try:
        # Calculate metrics
        total_requests = _metrics_state["verification_requests"]
        successes = _metrics_state["verification_successes"]
        success_rate = (successes / total_requests * 100) if total_requests > 0 else 0

        metrics = [
            MetricData(
                id="verification-success-rate",
                label="Verification Success Rate",
                value=success_rate,
                target=99.5,
                status="success" if success_rate >= 95 else "warning",
                description=f"{success_rate:.1f}% of verifications successful",
                actionUrl="/dashboard/verifications",
            ),
            MetricData(
                id="z3-solver-health",
                label="Z3 Solver Health",
                value=100 - (
                    _metrics_state["z3_solver_failures"] / max(total_requests, 1) * 100
                ),
                target=100,
                status="success"
                if _metrics_state["z3_solver_failures"] == 0
                else "danger",
                description=f"{_metrics_state['z3_solver_failures']} solver failures",
                actionUrl="/dashboard/solver",
            ),
            MetricData(
                id="average-solve-time",
                label="Average Solve Time",
                value=100 - min(_metrics_state["average_solve_time_ms"] / 10, 100),
                target=95,
                status="success"
                if _metrics_state["average_solve_time_ms"] < 100
                else "warning",
                description=f"{_metrics_state['average_solve_time_ms']:.1f}ms average",
                actionUrl="/dashboard/performance",
            ),
            MetricData(
                id="error-rate",
                label="Error Rate (24h)",
                value=100 - min(_metrics_state["errors_last_24h"] / max(total_requests / 1000, 1), 100),
                target=99.9,
                status="success"
                if _metrics_state["errors_last_24h"] < 10
                else "warning",
                description=f"{_metrics_state['errors_last_24h']} errors in 24h",
                actionUrl="/dashboard/errors",
            ),
        ]

        overall_health = sum(m.value for m in metrics) / len(metrics) if metrics else 0
        critical_issues = sum(1 for m in metrics if m.status == "danger")

        logger.debug(
            "Metrics computed",
            extra={
                "extra_data": {
                    "metrics_count": len(metrics),
                    "overall_health": overall_health,
                    "critical_issues": critical_issues,
                }
            },
        )

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
async def record_custom_metric(request: Request, metric_name: str, value: float) -> dict:
    """Record a custom metric."""
    try:
        update_metric(metric_name, value)
        return {"success": True, "metric": metric_name, "value": value}
    except Exception as exc:
        logger.error(f"Failed to record metric: {metric_name}", exc_info=exc)
        return {"success": False, "error": str(exc)}


__all__ = ["router", "update_metric", "increment_metric"]
