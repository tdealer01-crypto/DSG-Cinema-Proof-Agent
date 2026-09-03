from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse

UI_ROOT = Path(__file__).resolve().parents[1] / "market_ready_ui"


def _file(name: str, media_type: str) -> FileResponse:
    path = UI_ROOT / name
    if not path.exists():
        raise HTTPException(status_code=503, detail="Market-Ready UI bundle is not present in this image")
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


def install(app: Any) -> None:
    # api_v1.install(app) executes before cinema_main declares the legacy
    # /dashboard route, so this becomes the canonical customer surface while
    # preserving the old bundle on disk for rollback.
    @app.get("/dashboard", include_in_schema=False)
    async def market_ready_dashboard() -> FileResponse:
        response = _file("index.html", "text/html")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; frame-src https:; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'none'"
        )
        return response

    @app.get("/styles.css", include_in_schema=False)
    async def market_ready_styles() -> FileResponse:
        return _file("styles.css", "text/css")

    @app.get("/app.js", include_in_schema=False)
    async def market_ready_script() -> FileResponse:
        return _file("app.js", "application/javascript")

    @app.get("/config.js", include_in_schema=False)
    async def market_ready_config() -> FileResponse:
        return _file("config.js", "application/javascript")
