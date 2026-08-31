"""Data contracts for the RPi5 detection server.

PPEResult is the exact output schema from claude_code_prompt.md 4.2 — ③cloud/ and
④web/ both consume it, so field names/types must not change without updating both.
"""
from __future__ import annotations

from pydantic import BaseModel


class DetectResponse(BaseModel):
    """Immediate ack sent back to the ESP32 (API contract from 4.1)."""

    received: bool
    request_id: str


class PPEResult(BaseModel):
    request_id: str
    device_id: str
    timestamp: str
    helmet_detected: bool
    vest_detected: bool
    violation: bool
    confidence: float
    bbox: list[float]  # [x, y, w, h] in original image pixel coordinates
    image_ref: str      # local temp path (this process); not a public URL
    # Every raw YOLO detection this frame (Person, Hardhat, NO-Hardhat, Safety Vest,
    # NO-Safety Vest, ...) — [{label, confidence, box: [x,y,w,h]}, ...]. Lets ④web
    # draw a fully-labeled overlay instead of just the single primary bbox above.
    detections: list[dict] = []
