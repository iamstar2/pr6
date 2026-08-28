"""
Cloud 업로드 서비스.

inference 서비스가 violation=true 로 판정한 이벤트에 대해서만 호출한다.
정상(미착용 없음) 이미지는 이 서비스로 전달되지 않는다.
"""
import json
import logging

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

from .config import settings
from .supabase_client import SupabaseUploader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cloud")

app = FastAPI(title="PPE Detection Cloud Uploader")

_uploader = SupabaseUploader()


@app.get("/health")
async def health():
    status = "healthy" if _uploader.client is not None else "degraded"
    return {"status": status}


@app.post("/internal/violations")
async def create_violation(
    image: UploadFile = File(...),
    device_id: str = Form(...),
    captured_at: str = Form(""),
    violation_types: str = Form("[]"),
    max_confidence: str = Form("0.0"),
    detections: str = Form("[]"),
    model_name: str = Form(default=settings.MODEL_NAME),
    model_version: str = Form(default=settings.MODEL_VERSION),
):
    try:
        image_bytes = await image.read()
    except Exception as exc:  # noqa: BLE001
        logger.error("이미지 읽기 실패: %s", exc)
        return JSONResponse(
            status_code=400, content={"status": "error", "message": "이미지를 읽을 수 없습니다."}
        )

    if not image_bytes:
        return JSONResponse(
            status_code=400, content={"status": "error", "message": "빈 이미지입니다."}
        )

    try:
        violation_types_list = json.loads(violation_types)
        detections_list = json.loads(detections)
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "violation_types/detections JSON 파싱에 실패했습니다."},
        )

    record = {
        "captured_at": captured_at or None,
        "device_id": device_id,
        "violation_types": violation_types_list,
        "max_confidence": float(max_confidence),
        "detections": detections_list,
        "model_name": model_name,
        "model_version": model_version,
    }

    try:
        result = _uploader.upload_violation(image_bytes, record)
    except RuntimeError as exc:
        logger.error("Supabase 업로드 실패: %s", exc)
        return JSONResponse(status_code=502, content={"status": "error", "message": str(exc)})

    return {"status": "ok", "image_path": result["image_path"]}
