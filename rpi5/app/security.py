"""Auth + input-validation helpers for the ESP32-facing detect endpoint."""
from __future__ import annotations

import hmac
import re

from fastapi import Header, HTTPException

from app.config import get_config

# device_id ends up as a path segment in cloud storage keys (see
# cloud/providers/local_mock.py's `images_dir / key`). Without this check, a
# crafted value like "../../etc/whatever" is a path-traversal write primitive.
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_device_id(device_id: str) -> str:
    if not DEVICE_ID_PATTERN.match(device_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid device_id: must match ^[A-Za-z0-9_-]{1,64}$",
        )
    return device_id


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency: rejects the request unless X-API-Key matches DEVICE_API_KEY.

    DEVICE_API_KEY unset means auth is intentionally disabled (local dev only) —
    app.main logs a warning at startup in that case so it's never a silent gap.
    """
    expected = get_config().device_api_key
    if not expected:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")
