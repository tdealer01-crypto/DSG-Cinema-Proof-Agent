"""
Comprehensive Monitoring & Logging Module for DSG Z3 Solver Service
- Structured JSON logging
- Prometheus metrics
- Performance tracking
- Azure Application Insights integration (optional)
- Audit trail logging
"""

import os
import json
import time
import logging
import logging.handlers
from datetime import datetime
from typing import Dict, Any, Optional
from functools import wraps
from contextlib import contextmanager

from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# ============ CONFIG ============
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "/var/log/z3-solver/service.log")
ENABLE_AZURE_INSIGHTS = os.getenv("ENABLE_AZURE_INSIGHTS", "false").lower() == "true"
AZURE_INSTRUMENTATION_KEY = os.getenv("AZURE_INSTRUMENTATION_KEY", "")

# ============ LOGGING SETUP ============

def setup_logging():
    """Configure JSON structured logging"""
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)

    # Create logs directory if needed
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    # Console handler with JSON formatter
    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL)
    json_formatter = jsonlogger.JsonFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s %(extra)s',
        timestamp=True
    )
    console_handler.setFormatter(json_formatter)
    root_logger.addHandler(console_handler)

    # File handler with rotation
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=100_000_000,  # 100 MB
            backupCount=10
        )
        file_handler.setLevel(LOG_LEVEL)
        file_handler.setFormatter(json_formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        console_handler.emit(logging.LogRecord(
            name="logging_setup",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg=f"Failed to setup file logging: {e}",
            args=(),
            exc_info=None
        ))

    return root_logger

logger = setup_logging()

# Optional: Azure Application Insights integration
if ENABLE_AZURE_INSIGHTS and AZURE_INSTRUMENTATION_KEY:
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(
            instrumentation_key=AZURE_INSTRUMENTATION_KEY,
            disable_offline_storage=False,
        )
        logger.info("Azure Application Insights enabled")
    except Exception as e:
        logger.warning(f"Failed to initialize Azure Insights: {e}")

# ============ METRICS ============

# Solver metrics
solve_requests_total = Counter(
    'solver_requests_total',
    'Total number of solve requests',
    ['problem_type', 'status']
)

solve_duration_seconds = Histogram(
    'solver_duration_seconds',
    'Time spent solving problems',
    ['problem_type', 'status'],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
)

solve_queue_size = Gauge(
    'solver_queue_size',
    'Number of pending solve requests'
)

# Z3 specific metrics
z3_timeout_errors = Counter(
    'z3_timeout_errors_total',
    'Total Z3 timeout errors',
    ['problem_type']
)

z3_sat_results = Counter(
    'z3_sat_results_total',
    'Total SAT/UNSAT results',
    ['problem_type', 'result']
)

# API metrics
api_requests_total = Counter(
    'api_requests_total',
    'Total API requests',
    ['method', 'endpoint', 'status_code']
)

api_request_duration_seconds = Histogram(
    'api_request_duration_seconds',
    'API request duration',
    ['method', 'endpoint'],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
)

# Auth metrics
auth_failures_total = Counter(
    'auth_failures_total',
    'Total authentication failures',
    ['reason']
)

# Error metrics
errors_total = Counter(
    'errors_total',
    'Total errors by type',
    ['error_type']
)

# System metrics
active_requests = Gauge(
    'active_requests',
    'Number of active requests'
)

service_uptime_seconds = Gauge(
    'service_uptime_seconds',
    'Service uptime in seconds'
)

# ============ STRUCTURED LOGGING ============

class StructuredLogger:
    """Enhanced logger with structured context"""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.context = {}

    def set_context(self, **kwargs):
        """Set logging context"""
        self.context.update(kwargs)

    def clear_context(self):
        """Clear logging context"""
        self.context = {}

    def _log(self, level: int, message: str, **kwargs):
        """Internal logging method with context"""
        extra = {
            'extra': {
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'context': self.context,
                **kwargs
            }
        }
        self.logger.log(level, message, **extra)

    def debug(self, message: str, **kwargs):
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs):
        self._log(logging.CRITICAL, message, **kwargs)

# Global logger instance
service_logger = StructuredLogger("z3-solver-service")

# ============ DECORATORS ============

def track_performance(func):
    """Decorator to track function performance"""
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            duration = time.time() - start_time
            service_logger.info(
                f"Function {func.__name__} completed",
                duration_ms=int(duration * 1000),
                status="success"
            )
            return result
        except Exception as e:
            duration = time.time() - start_time
            service_logger.error(
                f"Function {func.__name__} failed",
                duration_ms=int(duration * 1000),
                error=str(e),
                error_type=type(e).__name__
            )
            errors_total.labels(error_type=type(e).__name__).inc()
            raise

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            service_logger.info(
                f"Function {func.__name__} completed",
                duration_ms=int(duration * 1000),
                status="success"
            )
            return result
        except Exception as e:
            duration = time.time() - start_time
            service_logger.error(
                f"Function {func.__name__} failed",
                duration_ms=int(duration * 1000),
                error=str(e),
                error_type=type(e).__name__
            )
            errors_total.labels(error_type=type(e).__name__).inc()
            raise

    import inspect
    if inspect.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper

# ============ CONTEXT MANAGERS ============

@contextmanager
def track_solver_operation(problem_type: str):
    """Context manager to track solver operations"""
    start_time = time.time()

    try:
        active_requests.inc()
        yield
    except Exception as e:
        service_logger.error(
            f"Solver operation failed for {problem_type}",
            error=str(e),
            error_type=type(e).__name__
        )
        errors_total.labels(error_type=type(e).__name__).inc()
        raise
    finally:
        duration = time.time() - start_time
        active_requests.dec()

# ============ MIDDLEWARE ============

class MonitoringMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for request/response monitoring"""

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()

        # Log request
        service_logger.info(
            f"API request: {request.method} {request.url.path}",
            method=request.method,
            path=request.url.path,
            client=request.client.host if request.client else "unknown"
        )

        active_requests.inc()

        try:
            response = await call_next(request)
            duration = time.time() - start_time

            # Record metrics
            api_requests_total.labels(
                method=request.method,
                endpoint=request.url.path,
                status_code=response.status_code
            ).inc()

            api_request_duration_seconds.labels(
                method=request.method,
                endpoint=request.url.path
            ).observe(duration)

            # Log response
            service_logger.info(
                f"API response: {request.method} {request.url.path} {response.status_code}",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=int(duration * 1000)
            )

            return response

        except Exception as e:
            duration = time.time() - start_time
            service_logger.error(
                f"API error: {request.method} {request.url.path}",
                method=request.method,
                path=request.url.path,
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=int(duration * 1000)
            )
            errors_total.labels(error_type=type(e).__name__).inc()
            raise

        finally:
            active_requests.dec()

# ============ AUDIT LOGGING ============

class AuditLogger:
    """Audit trail for security and compliance"""

    def __init__(self, log_name: str = "audit"):
        self.logger = StructuredLogger(log_name)

    def log_auth_attempt(self, request_id: str, success: bool, reason: str = ""):
        """Log authentication attempts"""
        if success:
            self.logger.info(
                "Authentication successful",
                request_id=request_id
            )
        else:
            self.logger.warning(
                f"Authentication failed: {reason}",
                request_id=request_id,
                reason=reason
            )
            auth_failures_total.labels(reason=reason).inc()

    def log_solve_request(
        self,
        request_id: str,
        problem_type: str,
        preset_name: str,
        status: str,
        compute_ms: int,
        energy: Optional[float] = None
    ):
        """Log solve requests with results"""
        self.logger.info(
            f"Solve request completed: {request_id}",
            request_id=request_id,
            problem_type=problem_type,
            preset_name=preset_name,
            status=status,
            compute_ms=compute_ms,
            energy=energy
        )

        solve_requests_total.labels(
            problem_type=problem_type,
            status=status
        ).inc()

        solve_duration_seconds.labels(
            problem_type=problem_type,
            status=status
        ).observe(compute_ms / 1000.0)

    def log_z3_result(self, problem_type: str, result: str):
        """Log Z3 solver results"""
        z3_sat_results.labels(
            problem_type=problem_type,
            result=result
        ).inc()

    def log_timeout(self, problem_type: str, timeout_ms: int):
        """Log Z3 timeout"""
        self.logger.warning(
            f"Z3 timeout for {problem_type}",
            problem_type=problem_type,
            timeout_ms=timeout_ms
        )
        z3_timeout_errors.labels(problem_type=problem_type).inc()

audit_logger = AuditLogger()

# ============ HEALTH CHECKS ============

class HealthCheckStatus:
    """Service health status"""

    def __init__(self):
        self.start_time = time.time()
        self.last_successful_solve = None
        self.error_count = 0
        self.request_count = 0

    def get_status(self) -> Dict[str, Any]:
        """Get current health status"""
        uptime = time.time() - self.start_time
        service_uptime_seconds.set(uptime)

        return {
            "status": "healthy" if self.error_count < 10 else "degraded",
            "uptime_seconds": int(uptime),
            "uptime_human": self._format_uptime(uptime),
            "total_requests": self.request_count,
            "error_count": self.error_count,
            "last_successful_solve": self.last_successful_solve,
            "error_rate": (
                self.error_count / self.request_count
                if self.request_count > 0 else 0
            )
        }

    @staticmethod
    def _format_uptime(seconds: int) -> str:
        """Format uptime as human readable"""
        hours, remainder = divmod(int(seconds), 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}h {minutes}m {secs}s"

    def record_request(self, success: bool = True):
        """Record request"""
        self.request_count += 1
        if not success:
            self.error_count += 1
        if success:
            self.last_successful_solve = datetime.utcnow().isoformat() + 'Z'

health_check = HealthCheckStatus()

# ============ METRICS EXPORT ============

def get_metrics() -> str:
    """Export Prometheus metrics"""
    return generate_latest().decode('utf-8')

def get_metrics_content_type() -> str:
    """Get Prometheus metrics content type"""
    return CONTENT_TYPE_LATEST
