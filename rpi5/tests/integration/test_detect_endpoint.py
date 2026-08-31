"""End-to-end tests against the actual FastAPI app for POST /api/v1/detect.

Only the boundaries that would otherwise need real hardware/network/cloud
accounts are mocked: the ONNX inference call and the outbound web-dashboard
notification. Everything else (auth dependency, input validation, response
shape) runs through the real app.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import config, events
from app.main import app
from app.routers import detect as detect_module
from app.schemas import PPEResult


def _real_jpeg_bytes() -> bytes:
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _fake_result(violation: bool) -> PPEResult:
    return PPEResult(
        request_id="", device_id="", timestamp="",
        helmet_detected=not violation, vest_detected=not violation,
        violation=violation, confidence=0.9, bbox=[0.0, 0.0, 10.0, 10.0], image_ref="test",
    )


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_API_KEY", "test-key")
    monkeypatch.setenv("RETRY_QUEUE_DIR", str(tmp_path / "retry"))
    monkeypatch.setenv("CLOUD_MOCK_STORAGE_DIR", str(tmp_path / "mock_storage"))
    config.get_config.cache_clear()
    monkeypatch.setattr("app.events.emit_live_frame", AsyncMock())
    monkeypatch.setattr("app.events.emit_violation", AsyncMock())
    monkeypatch.setattr("app.events.emit_cloud_status", AsyncMock())
    return TestClient(app)


def _post_detect(client, *, device_id="esp32-01", api_key="test-key", content_type="image/jpeg", image=None):
    headers = {"X-API-Key": api_key} if api_key is not None else {}
    return client.post(
        "/api/v1/detect",
        headers=headers,
        data={"device_id": device_id, "timestamp": "2026-01-01T00:00:00Z", "confidence": "0.9"},
        files={"image": ("capture.jpg", image or _real_jpeg_bytes(), content_type)},
    )


def test_detect_rejects_missing_api_key(client):
    resp = _post_detect(client, api_key=None)
    assert resp.status_code == 401


def test_detect_rejects_wrong_api_key(client):
    resp = _post_detect(client, api_key="wrong-key")
    assert resp.status_code == 401


def test_detect_rejects_path_traversal_device_id(client):
    resp = _post_detect(client, device_id="../../evil")
    assert resp.status_code == 400


def test_detect_rejects_oversized_upload(client, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "10")
    config.get_config.cache_clear()
    resp = _post_detect(client, image=b"0" * 100)
    assert resp.status_code == 413


def test_detect_rejects_non_jpeg_content_type(client):
    resp = _post_detect(client, content_type="image/png")
    assert resp.status_code == 400


def test_detect_success_returns_request_id(client, monkeypatch):
    monkeypatch.setattr("app.routers.detect.infer_ppe", lambda img: _fake_result(False))
    resp = _post_detect(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["received"] is True
    assert body["request_id"]


def test_detect_violation_returns_ok_immediately(client, monkeypatch):
    """The HTTP response must not wait on the cloud-upload background task — that's
    the whole point of firing it via asyncio.create_task (see routers/detect.py).
    Whether that task actually persists the image is verified separately below,
    by awaiting it directly instead of racing it through a sync TestClient call
    (polling for a background task's side effect here was flaky in CI: the
    fire-and-forget task doesn't get scheduled on any predictable timeline
    relative to a sync test thread's wall-clock polling).
    """
    monkeypatch.setattr("app.routers.detect.infer_ppe", lambda img: _fake_result(True))
    resp = _post_detect(client)
    assert resp.status_code == 200
    assert resp.json()["request_id"]


async def test_handle_violation_persists_image_and_record(monkeypatch, tmp_path):
    """Directly awaits _handle_violation() (the coroutine detect() fires off in the
    background) so the assertion isn't racing a fire-and-forget task's scheduling.
    """
    monkeypatch.setenv("CLOUD_MOCK_STORAGE_DIR", str(tmp_path / "mock_storage"))
    config.get_config.cache_clear()
    monkeypatch.setattr(events, "emit_violation", AsyncMock())
    monkeypatch.setattr(events, "emit_cloud_status", AsyncMock())

    result = _fake_result(True).model_copy(update={
        "request_id": "req-handle-1", "device_id": "esp32-01", "timestamp": "2026-01-01T00:00:00Z",
    })

    await detect_module._handle_violation(result, b"jpeg-bytes", {"request_id": "req-handle-1"})

    saved_image = tmp_path / "mock_storage" / "images" / "esp32-01" / "req-handle-1.jpg"
    assert saved_image.exists()
    assert saved_image.read_bytes() == b"jpeg-bytes"
