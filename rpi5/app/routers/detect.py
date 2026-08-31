from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid

import cv2
import numpy as np
from cloud.factory import get_storage_provider
from cloud.schemas import ViolationRecord
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app import events, retry_queue
from app.config import get_config
from app.inference import infer_ppe
from app.schemas import DetectResponse, PPEResult
from app.security import require_api_key, validate_device_id

logger = logging.getLogger("rpi5.detect")

router = APIRouter(dependencies=[Depends(require_api_key)])

# Dedup for "same person still standing there" — there's no real person
# re-identification model here, so this approximates it with bbox overlap: if a
# new violation's box heavily overlaps the last one we actually saved for this
# device within the window below, treat it as the same ongoing violation and
# skip re-saving/re-alerting (still counted as "seen" so the window keeps
# sliding while they stay). A genuinely different person (different position)
# or the same person after a long gap triggers a fresh save.
_DEDUP_WINDOW_SECONDS = 30.0
_DEDUP_IOU_THRESHOLD = 0.5
_last_violation_by_device: dict[str, dict] = {}


def _iou(box_a: list[float], box_b: list[float]) -> float:
    """Intersection-over-union between two [x, y, w, h] boxes."""
    ax0, ay0, aw, ah = box_a
    bx0, by0, bw, bh = box_b
    inter_x0, inter_y0 = max(ax0, bx0), max(ay0, by0)
    inter_x1, inter_y1 = min(ax0 + aw, bx0 + bw), min(ay0 + ah, by0 + bh)
    inter_area = max(0.0, inter_x1 - inter_x0) * max(0.0, inter_y1 - inter_y0)
    if inter_area <= 0:
        return 0.0
    union_area = aw * ah + bw * bh - inter_area
    return inter_area / union_area if union_area > 0 else 0.0


def _is_same_ongoing_violation(device_id: str, bbox: list[float]) -> bool:
    last = _last_violation_by_device.get(device_id)
    if last is None or time.monotonic() - last["seen_at"] > _DEDUP_WINDOW_SECONDS:
        return False
    return _iou(bbox, last["bbox"]) >= _DEDUP_IOU_THRESHOLD


@router.post("/api/v1/detect", response_model=DetectResponse)
async def detect(
    image: UploadFile = File(...),
    device_id: str = Form(...),
    timestamp: str = Form(...),
    confidence: float = Form(...),
) -> DetectResponse:
    """Receives one capture from ①ESP32 (see API contract in README 4.1), runs PPE
    inference, and fans the result out to ③cloud (violations only) and ④web (always).
    Responds to the ESP32 immediately — downstream fan-out runs in the background so
    a slow cloud upload or an unreachable web backend never blocks the camera node.
    """
    device_id = validate_device_id(device_id)
    request_id = str(uuid.uuid4())
    image_bytes = await image.read()

    cfg = get_config()
    if len(image_bytes) > cfg.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Image size {len(image_bytes)}B exceeds max_upload_bytes={cfg.max_upload_bytes}",
        )
    if image.content_type not in ("image/jpeg", "image/jpg"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content_type={image.content_type!r}, expected image/jpeg",
        )

    img = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Could not decode image as JPEG")

    # infer_ppe() runs onnxruntime + OpenCV synchronously — to_thread hands it to a
    # worker thread so one slow inference doesn't stall the event loop (and with it,
    # every other device's request and the background event-emit tasks below).
    result = await asyncio.to_thread(infer_ppe, img)
    labels_seen = [d["label"] for d in result.detections]
    logger.info(
        "request_id=%s device_id=%s labels=%s helmet=%s vest=%s violation=%s conf=%.2f",
        request_id, device_id, labels_seen,
        result.helmet_detected, result.vest_detected, result.violation, result.confidence,
    )
    result = result.model_copy(update={
        "request_id": request_id,
        "device_id": device_id,
        "timestamp": timestamp,
        "image_ref": f"memory:{request_id} ({result.image_ref})",
    })

    # ESP32 already sends this exact image on every person-detection (not just
    # violations) — relaying it to the web dashboard costs the camera node nothing
    # extra. Sent as base64 in the socket payload (not persisted to cloud storage;
    # only violations get saved there) so the live view shows the real capture
    # instead of a coordinate-only mock overlay.
    img_h, img_w = img.shape[:2]
    live_payload = {
        **result.model_dump(),
        "image_base64": base64.b64encode(image_bytes).decode("ascii"),
        "image_width": img_w,
        "image_height": img_h,
    }

    asyncio.create_task(events.emit_live_frame(live_payload))
    if result.violation:
        if _is_same_ongoing_violation(device_id, result.bbox):
            logger.info(
                "Skipping duplicate violation for device_id=%s (same spot within %.0fs)",
                device_id, _DEDUP_WINDOW_SECONDS,
            )
            _last_violation_by_device[device_id]["seen_at"] = time.monotonic()
        else:
            _last_violation_by_device[device_id] = {"bbox": result.bbox, "seen_at": time.monotonic()}
            asyncio.create_task(_handle_violation(result, image_bytes, live_payload))

    return DetectResponse(received=True, request_id=request_id)


def _violation_type(result: PPEResult) -> str:
    if not result.helmet_detected and not result.vest_detected:
        return "no_helmet_no_vest"
    if not result.helmet_detected:
        return "no_helmet"
    return "no_vest"


async def _handle_violation(result: PPEResult, image_bytes: bytes, live_payload: dict) -> None:
    await events.emit_violation(live_payload)

    provider = get_storage_provider()
    key = f"{result.device_id}/{result.request_id}.jpg"
    record = ViolationRecord(
        id=result.request_id,
        device_id=result.device_id,
        timestamp=result.timestamp,
        helmet_detected=result.helmet_detected,
        vest_detected=result.vest_detected,
        image_url="",
        violation_type=_violation_type(result),
    )
    logger.info(
        "Saving violation request_id=%s via provider=%s bucket=%s key=%s",
        result.request_id, type(provider).__name__, getattr(provider, "bucket", "?"), key,
    )
    status, image_url = "success", ""
    try:
        image_url = await provider.upload_image(image_bytes, key=key)
        logger.info("upload_image() OK for request_id=%s -> %s", result.request_id, image_url)
        await provider.save_record(record.model_copy(update={"image_url": image_url}))
        logger.info("save_record() OK for request_id=%s", result.request_id)
    except Exception:
        logger.exception(
            "Cloud storage upload/save failed for request_id=%s — queuing for retry",
            result.request_id,
        )
        status = "failed"
        # Graceful degradation: don't drop the violation just because cloud storage
        # is down right now — persist it and let retry_queue.run_forever() catch it
        # up later. The detection pipeline itself already returned to the ESP32
        # long before this function even started running.
        await retry_queue.enqueue(image_bytes, record)

    await events.emit_cloud_status({
        "request_id": result.request_id,
        "device_id": result.device_id,
        "status": status,
        "image_url": image_url,
        "timestamp": result.timestamp,
    })
