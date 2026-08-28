"""
YOLO ONNX 추론 서비스.

receiver로부터 JPEG 이미지를 받아 PPE 미착용 여부를 판정하고,
violation이 발생한 경우에만 cloud 서비스로 이미지+메타데이터를 전달한다.
"""
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse

from .config import settings
from .detector import CooldownTracker, PPEDetector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("inference")

_detector: Optional[PPEDetector] = None
_model_load_error: Optional[str] = None
_cooldown = CooldownTracker(settings.EVENT_COOLDOWN_SEC)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    컨테이너 기동 시 1회만 모델을 로드한다.
    best.onnx가 없어도 서비스 자체는 뜨게 하고, 실제 추론 요청 시 명확한 오류를 반환한다.
    """
    global _detector, _model_load_error
    try:
        _detector = PPEDetector()
    except Exception as exc:  # noqa: BLE001
        _model_load_error = str(exc)
        logger.error("모델 로드 실패: %s", exc)
    yield


app = FastAPI(title="PPE Detection Inference", lifespan=lifespan)


@app.get("/health")
async def health():
    if _detector is None:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "message": _model_load_error or "모델이 로드되지 않았습니다."},
        )
    return {"status": "healthy"}


async def _upload_to_cloud(
    annotated_image: bytes,
    device_id: str,
    captured_at: Optional[str],
    violation_types: list[str],
    detections: list[dict],
    max_confidence: float,
) -> dict:
    """violation=true일 때만 호출되는 cloud 내부 API 연동."""
    files = {"image": ("violation.jpg", annotated_image, "image/jpeg")}
    data = {
        "device_id": device_id,
        "captured_at": captured_at or "",
        "violation_types": json.dumps(violation_types),
        "max_confidence": str(max_confidence),
        "detections": json.dumps(detections),
        "model_name": settings.MODEL_NAME,
        "model_version": settings.MODEL_VERSION,
    }
    async with httpx.AsyncClient(timeout=settings.CLOUD_TIMEOUT_SEC) as client:
        response = await client.post(
            f"{settings.CLOUD_URL}/internal/violations", data=data, files=files
        )
    response.raise_for_status()
    return response.json()


@app.post("/internal/infer")
async def infer(
    request: Request,
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-ID"),
    x_captured_at: Optional[str] = Header(default=None, alias="X-Captured-At"),
):
    if _detector is None:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"모델 파일을 로드할 수 없습니다: {_model_load_error}",
            },
        )

    image_bytes = await request.body()
    if not image_bytes:
        return JSONResponse(
            status_code=400, content={"status": "error", "message": "빈 이미지입니다."}
        )

    device_id = x_device_id or "unknown-device"

    try:
        result = _detector.detect(image_bytes)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001
        logger.error("ONNX Runtime 추론 오류: %s", exc)
        return JSONResponse(
            status_code=500, content={"status": "error", "message": "추론 중 오류가 발생했습니다."}
        )

    event_id = str(uuid.uuid4())
    response: dict = {
        "event_id": event_id,
        "ppe_status": result["ppe_status"],
        "violation": result["violation"],
        "violation_types": result["violation_types"],
        "detections": result["detections"],
    }

    if not result["violation"]:
        # ppe_status는 COMPLIANT(착용) 또는 NO_PERSON(이상없음) 둘 중 하나이며,
        # 두 경우 모두 Supabase에는 전달하지 않는다.
        response["cloud_uploaded"] = False
        response["reason"] = "no_violation"
        return response

    cooldown_key = (device_id, tuple(result["violation_types"]))
    if _cooldown.is_cooling_down(cooldown_key):
        response["cloud_uploaded"] = False
        response["reason"] = "cooldown"
        return response

    max_confidence = max(
        (d["confidence"] for d in result["detections"] if d["violation_type"]),
        default=0.0,
    )

    # cloud 저장이 실패하더라도 AI 추론 결과 자체는 response에 그대로 유지한다.
    try:
        cloud_result = await _upload_to_cloud(
            result["annotated_image"],
            device_id,
            x_captured_at,
            result["violation_types"],
            result["detections"],
            max_confidence,
        )
        _cooldown.mark_uploaded(cooldown_key)
        response["cloud_uploaded"] = True
        response["cloud_result"] = cloud_result
    except httpx.RequestError as exc:
        logger.error("cloud 서비스 연결 실패: %s", exc)
        response["cloud_uploaded"] = False
        response["cloud_error"] = "cloud 서비스에 연결할 수 없습니다."
    except httpx.HTTPStatusError as exc:
        logger.error("cloud 서비스 오류 응답: %s", exc)
        response["cloud_uploaded"] = False
        response["cloud_error"] = "cloud 서비스가 오류를 반환했습니다."

    return response
