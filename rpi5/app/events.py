"""Forwards detection results to the web dashboard's backend, which re-broadcasts
them over Socket.IO as `violation_detected` / `cloud_upload_status` / `live_detection_frame`.

Best-effort: a web backend outage must never break the ESP32 -> RPi5 -> cloud path,
so every call here swallows its own errors (logged, not raised).
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import get_config

logger = logging.getLogger("rpi5.events")

_client = httpx.AsyncClient(timeout=5.0)  # live-frame/violation payloads now embed a base64 image


async def _post(path: str, payload: dict) -> None:
    """Best-effort notify: a web-dashboard outage must never break the ESP32 ->
    RPi5 -> cloud path, so this retries a few times with backoff and then swallows
    the failure (logged, not raised) rather than queuing forever — these are live
    telemetry events, not the violation evidence itself (that's cloud_status's job
    via retry_queue, which does persist).
    """
    cfg = get_config()
    url = f"{cfg.web_backend_url}{path}"
    headers = {"X-Internal-Token": cfg.web_ingress_token} if cfg.web_ingress_token else {}
    backoff = cfg.web_event_backoff_base_seconds
    for attempt in range(1, cfg.web_event_max_retries + 1):
        try:
            resp = await _client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return
        except httpx.HTTPError as exc:
            if attempt == cfg.web_event_max_retries:
                logger.warning(
                    "Failed to notify web backend at %s after %d attempt(s): %s", url, attempt, exc
                )
                return
            logger.debug(
                "Web backend notify attempt %d/%d failed (%s), retrying in %.1fs",
                attempt, cfg.web_event_max_retries, exc, backoff,
            )
            await asyncio.sleep(backoff)
            backoff *= 2


async def emit_live_frame(payload: dict) -> None:
    await _post("/api/events/live-frame", payload)


async def emit_violation(payload: dict) -> None:
    await _post("/api/events/violation", payload)


async def emit_cloud_status(payload: dict) -> None:
    await _post("/api/events/cloud-status", payload)
