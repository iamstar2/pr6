"""
receiver 서비스 테스트.

inference 서비스는 실제로 띄우지 않고 `_forward_to_inference`를 monkeypatch로 대체한다.
"""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

RECEIVER_ROOT = Path(__file__).resolve().parents[1] / "receiver"


def _load_receiver_app():
    """
    receiver/inference/cloud가 모두 'app' 이라는 동일한 패키지 이름을 쓰기 때문에,
    다른 테스트 파일이 먼저 import한 'app' 캐시와 충돌하지 않도록 매번 초기화한다.
    """
    sys.path.insert(0, str(RECEIVER_ROOT))
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    import app.main as receiver_main

    return receiver_main


receiver_main = _load_receiver_app()


def _make_jpeg_bytes() -> bytes:
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    success, buffer = cv2.imencode(".jpg", image)
    assert success
    return buffer.tobytes()


@pytest.fixture
def client(monkeypatch):
    async def fake_forward(image_bytes, device_id, captured_at):
        return {
            "event_id": "test-event-id",
            "violation": False,
            "violation_types": [],
            "detections": [],
            "cloud_uploaded": False,
            "reason": "no_violation",
        }

    monkeypatch.setattr(receiver_main, "_forward_to_inference", fake_forward)
    return TestClient(receiver_main.app)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_receive_raw_jpeg(client):
    """기본 방식: raw image/jpeg binary body."""
    jpeg_bytes = _make_jpeg_bytes()
    response = client.post(
        "/api/v1/frame",
        content=jpeg_bytes,
        headers={"Content-Type": "image/jpeg", "X-Device-ID": "esp32-s3-01"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["device_id"] == "esp32-s3-01"
    assert body["violation"] is False


def test_receive_multipart_jpeg(client):
    """대안 방식: multipart/form-data의 file 필드."""
    jpeg_bytes = _make_jpeg_bytes()
    response = client.post(
        "/api/v1/frame",
        files={"file": ("frame.jpg", jpeg_bytes, "image/jpeg")},
        headers={"X-Device-ID": "esp32-s3-01"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_receive_invalid_image_returns_400(client):
    response = client.post(
        "/api/v1/frame",
        content=b"this is not a jpeg image",
        headers={"Content-Type": "image/jpeg"},
    )
    assert response.status_code == 400


def test_receive_empty_body_returns_400(client):
    response = client.post(
        "/api/v1/frame",
        content=b"",
        headers={"Content-Type": "image/jpeg"},
    )
    assert response.status_code == 400
