"""Data contracts for the cloud storage module.

These are shared between the RPi5 pipeline (caller) and any CloudStorageProvider
implementation (callee). Keep this file provider-agnostic.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ViolationRecord(BaseModel):
    """Metadata persisted for a single PPE violation (helmet/vest not detected).

    Mirrors the "위반 기록 메타데이터" contract from the spec:
    {id, device_id, timestamp, helmet_detected, vest_detected, image_url, violation_type}
    """

    id: str = Field(..., description="Unique record id (use the RPi5 request_id)")
    device_id: str
    timestamp: str = Field(..., description="ISO8601 timestamp")
    helmet_detected: bool
    vest_detected: bool
    image_url: str = Field(..., description="URL returned by upload_image()")
    violation_type: str = Field(
        ..., description="e.g. 'no_helmet', 'no_vest', 'no_helmet_no_vest'"
    )
