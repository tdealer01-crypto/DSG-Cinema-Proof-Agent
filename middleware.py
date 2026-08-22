"""FastAPI middleware for request tracking and error handling."""

from __future__ import annotations

import time
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from logging_config import LogContext, generate_request_id, logger


class RequestTrackingMiddleware(BaseHTTPMiddleware):
    """Middleware that adds request ID tracking and logs all requests."""

    async def dispatch(self, request: Request, call_next: Callable) -> JSONResponse:
        request_id = generate_request_id()
        start_time = time.time()

        # Add request_id to request state
        request.state.request_id = request_id

        # Log request
        logger.info(
            f"{request.method} {request.url.path}",
            extra={
                "request_id": request_id,
                "extra_data": {
                    "method": request.method,
                    "path": request.url.path,
                    "client": request.client.host if request.client else "unknown",
                },
            },
        )

        try:
            response = await call_next(request)
            duration = time.time() - start_time

            # Log successful response
            logger.info(
                f"{request.method} {request.url.path} {response.status_code}",
                extra={
                    "request_id": request_id,
                    "extra_data": {
                        "status_code": response.status_code,
                        "duration_ms": duration * 1000,
                    },
                },
            )

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as exc:
            duration = time.time() - start_time
            logger.error(
                f"{request.method} {request.url.path} failed",
                exc_info=exc,
                extra={
                    "request_id": request_id,
                    "extra_data": {
                        "duration_ms": duration * 1000,
                        "error": str(exc),
                    },
                },
            )
            raise


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Middleware that handles exceptions and returns appropriate JSON responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> JSONResponse:
        try:
            return await call_next(request)
        except ValueError as exc:
            request_id = getattr(request.state, "request_id", "unknown")
            logger.warning(
                f"Validation error: {exc}",
                extra={
                    "request_id": request_id,
                    "extra_data": {"error_type": "validation", "message": str(exc)},
                },
            )
            return JSONResponse(
                status_code=400,
                content={
                    "error": str(exc),
                    "code": "VALIDATION_ERROR",
                    "request_id": request_id,
                },
            )
        except Exception as exc:
            request_id = getattr(request.state, "request_id", "unknown")
            logger.error(
                f"Unhandled error: {exc}",
                exc_info=exc,
                extra={"request_id": request_id},
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal server error",
                    "code": "INTERNAL_ERROR",
                    "request_id": request_id,
                },
            )


__all__ = ["RequestTrackingMiddleware", "ErrorHandlingMiddleware"]
