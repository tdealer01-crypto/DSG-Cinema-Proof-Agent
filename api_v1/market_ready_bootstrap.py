from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
from typing import Any


def install(app: Any) -> None:
    """Configure and mount the Market-Ready provisioner without new credentials.

    A dedicated DSG_PROVISIONER_SECRET wins when configured. Otherwise Cinema
    derives a distinct HMAC key from the already-required DSG_BACKEND_API_KEY
    using a fixed domain separator. The backend secret itself is never reused as
    the callback key and is never persisted by this module.
    """
    from . import market_ready_platform as platform

    # Production clones the exact reconstructed Market-Ready product shell, not
    # the legacy customer-dashboard bundle. This keeps provisioner source lineage
    # aligned with the product customers actually see.
    platform.TEMPLATE = Path(__file__).resolve().parents[1] / "market_ready_ui"

    dedicated = os.getenv("DSG_PROVISIONER_SECRET", "").strip()
    if len(dedicated) >= 32:
        platform.MASTER_SECRET_RAW = dedicated
        platform.MASTER_SECRET = dedicated.encode("utf-8")
    else:
        backend = os.getenv("DSG_BACKEND_API_KEY", "").strip()
        if len(backend) >= 32:
            derived = hmac.new(
                backend.encode("utf-8"),
                b"dsg-market-ready-provisioner-v1",
                hashlib.sha256,
            ).digest()
            platform.MASTER_SECRET_RAW = "derived:" + derived.hex()
            platform.MASTER_SECRET = derived
    platform.install(app)
