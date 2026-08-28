"""
- violation 판정 로직 (inference/app/detector.py) 테스트
- 정상 이미지는 cloud로 전송되지 않는지 테스트 (inference/app/main.py)
- Supabase 업로드 payload 생성 테스트 (cloud/app/main.py)

실제 ONNX 모델, 실제 Supabase key 없이 Mock만으로 동작해야 한다.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

INFERENCE_ROOT = Path(__file__).resolve().parents[1] / "inference"
CLOUD_ROOT = Path(__file__).resolve().parents[1] / "cloud"


def _reset_app_cache():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


def _load_inference_detector():
    sys.path.insert(0, str(INFERENCE_ROOT))
    _reset_app_cache()
    import app.detector as detector

    return detector


def _load_inference_main():
    sys.path.insert(0, str(INFERENCE_ROOT))
    _reset_app_cache()
    import app.main as inference_main

    return inference_main


def _load_cloud_main():
    sys.path.insert(0, str(CLOUD_ROOT))
    _reset_app_cache()
    import app.main as cloud_main

    return cloud_main


def _make_jpeg_bytes() -> bytes:
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    success, buffer = cv2.imencode(".jpg", image)
    assert success
    return buffer.tobytes()


# ---------------------------------------------------------------------------
# 1. violation 판정 테스트 (실제 ONNX 모델 없이 class 매핑 로직만 검증)
# ---------------------------------------------------------------------------
def test_violation_classification():
    detector_module = _load_inference_detector()

    # PPEDetector.__init__은 실제 ONNX 모델 로드를 시도하므로,
    # class 매핑 로직만 검증하기 위해 __init__을 거치지 않고 인스턴스를 만든다.
    detector = object.__new__(detector_module.PPEDetector)
    detector._no_helmet_names = {"no-hardhat"}
    detector._no_vest_names = {"no-safety vest"}
    detector._person_names = {"person"}

    assert detector._classify("NO-Hardhat") == detector_module.VIOLATION_NO_HARDHAT
    assert detector._classify("NO-Safety Vest") == detector_module.VIOLATION_NO_SAFETY_VEST
    assert detector._classify("Hardhat") is None
    assert detector._classify("Person") is None
    assert detector._is_person("Person") is True
    assert detector._is_person("Hardhat") is False


def test_determine_status_requires_person_for_violation():
    """
    사람(person)이 감지되지 않으면 미착용 class가 잡혀도 'NO_PERSON'(이상없음)이어야 하고,
    Supabase 업로드 대상인 'VIOLATION'은 사람이 감지된 경우에만 나와야 한다.
    """
    determine_status = _load_inference_detector().determine_status

    # 사람 없이 방치된 안전모 물체만 미착용 class로 잡힌 경우 -> 이상없음 (오탐 방지)
    assert determine_status(has_person=False, violation_types={"NO_HARDHAT"}) == "NO_PERSON"
    # 사람도 없고 미착용도 없는 경우 -> 이상없음
    assert determine_status(has_person=False, violation_types=set()) == "NO_PERSON"
    # 사람 감지 + 미착용 -> 미착용(Supabase 전달 대상)
    assert determine_status(has_person=True, violation_types={"NO_HARDHAT"}) == "VIOLATION"
    # 사람 감지 + 미착용 없음 -> 착용
    assert determine_status(has_person=True, violation_types=set()) == "COMPLIANT"


# ---------------------------------------------------------------------------
# 2. 정상 이미지는 cloud로 전송되지 않는지 테스트
# ---------------------------------------------------------------------------
class _FakeDetector:
    def detect(self, image_bytes: bytes) -> dict:
        return {
            "ppe_status": "NO_PERSON",
            "violation": False,
            "violation_types": [],
            "detections": [],
            "annotated_image": None,
        }


@pytest.fixture
def inference_client(monkeypatch):
    inference_main = _load_inference_main()
    monkeypatch.setattr(inference_main, "PPEDetector", lambda: _FakeDetector())
    with TestClient(inference_main.app) as client:
        yield client, inference_main


def test_no_violation_skips_cloud_upload(inference_client, monkeypatch):
    client, inference_main = inference_client

    upload_calls = []

    async def fake_upload(*args, **kwargs):
        upload_calls.append((args, kwargs))
        return {"image_path": "should-not-be-called"}

    monkeypatch.setattr(inference_main, "_upload_to_cloud", fake_upload)

    response = client.post(
        "/internal/infer",
        content=_make_jpeg_bytes(),
        headers={"X-Device-ID": "esp32-s3-01"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ppe_status"] == "NO_PERSON"
    assert body["violation"] is False
    assert body["cloud_uploaded"] is False
    assert body["reason"] == "no_violation"
    assert upload_calls == []  # cloud 업로드 함수가 호출되지 않아야 한다.


# ---------------------------------------------------------------------------
# 3. Supabase 업로드 payload 생성 테스트 (cloud 서비스)
# ---------------------------------------------------------------------------
def test_cloud_service_builds_payload_and_returns_image_path(monkeypatch):
    cloud_main = _load_cloud_main()

    captured = {}

    def fake_upload_violation(image_bytes: bytes, record: dict) -> dict:
        captured["image_bytes"] = image_bytes
        captured["record"] = record
        return {"image_path": "2026/08/28/fake-uuid.jpg"}

    monkeypatch.setattr(cloud_main._uploader, "upload_violation", fake_upload_violation)

    with TestClient(cloud_main.app) as client:
        response = client.post(
            "/internal/violations",
            files={"image": ("violation.jpg", _make_jpeg_bytes(), "image/jpeg")},
            data={
                "device_id": "esp32-s3-01",
                "captured_at": "2026-08-28T10:00:00Z",
                "violation_types": json.dumps(["NO_HARDHAT"]),
                "max_confidence": "0.87",
                "detections": json.dumps(
                    [
                        {
                            "class_name": "NO-Hardhat",
                            "violation_type": "NO_HARDHAT",
                            "confidence": 0.87,
                            "bbox": {"x1": 1, "y1": 2, "x2": 3, "y2": 4},
                        }
                    ]
                ),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["image_path"] == "2026/08/28/fake-uuid.jpg"

    record = captured["record"]
    assert record["device_id"] == "esp32-s3-01"
    assert record["violation_types"] == ["NO_HARDHAT"]
    assert record["max_confidence"] == pytest.approx(0.87)
    assert record["detections"][0]["class_name"] == "NO-Hardhat"
