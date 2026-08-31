"""Same-origin HTML surface for DSG Live.

The browser keeps the session token in the URL fragment and sends it only in the
`X-DSG-Live-Token` header to the same Cinema origin. No cross-origin token CORS
surface is required.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.responses import FileResponse

PRODUCTION_ORIGIN = "https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io"
MONITOR_FILE = Path(__file__).with_name("live.html")


def install(app) -> None:
    from . import live_monitor

    # `create_live_session` appends /live.html#<token>. Keep the default on the
    # Cinema API origin; operators can override the origin for staging/local use.
    live_monitor.DEFAULT_MONITOR_ORIGIN = (
        os.getenv("DSG_LIVE_MONITOR_ORIGIN") or PRODUCTION_ORIGIN
    ).strip().rstrip("/")

    @app.get("/live.html", include_in_schema=False)
    async def dsg_live_monitor_page():
        return FileResponse(
            MONITOR_FILE,
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )
