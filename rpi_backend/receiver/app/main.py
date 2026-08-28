"""
Raspberry Pi HTTP Receiver.

ESP32-S3로부터 JPEG 이미지를 받아 inference 서비스로 전달하는 게이트웨이 역할만 한다.
이미지를 자체적으로 저장하지 않는다 (저장은 violation 발생 시 cloud 서비스가 담당).

ESP32 팀원의 구현 방식이 확정되지 않았을 수 있으므로
1) raw image/jpeg binary
2) multipart/form-data (file 필드)
두 가지 방식을 모두 지원한다.
"""
import logging

import cv2
import httpx
import numpy as np
from fastapi import FastAPI, Request, UploadFile, File, Header
from fastapi.responses import JSONResponse
from typing import Optional

from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("receiver")

app = FastAPI(title="PPE Detection Receiver")


def _decode_check(image_bytes: bytes) -> bool:
    """OpenCV로 decode 가능한 JPEG인지 확인한다 (실제 픽셀 디코딩은 inference에서 다시 수행)."""
    if not image_bytes:
        return False
    np_arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    return img is not None


async def _forward_to_inference(
    image_bytes: bytes, device_id: str, captured_at: Optional[str]
) -> dict:
    """디코딩이 확인된 이미지를 inference 컨테이너의 내부 API로 전달한다."""
    url = f"{settings.INFERENCE_URL}/internal/infer"
    headers = {"X-Device-ID": device_id}
    if captured_at:
        headers["X-Captured-At"] = captured_at

    async with httpx.AsyncClient(timeout=settings.INFERENCE_TIMEOUT_SEC) as client:
        response = await client.post(
            url,
            content=image_bytes,
            headers={**headers, "Content-Type": "image/jpeg"},
        )
    response.raise_for_status()
    return response.json()


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/api/v1/frame")
async def receive_frame(
    request: Request,
    x_device_id: Optional[str] = Header(default=None, alias="X-Device-ID"),
    x_captured_at: Optional[str] = Header(default=None, alias="X-Captured-At"),
    file: Optional[UploadFile] = File(default=None),
):
    """
    ESP32-S3로부터 JPEG 프레임을 수신한다.

    - Content-Type이 multipart/form-data이면 `file` 필드에서 읽는다.
    - 그 외에는 raw body를 JPEG binary로 간주한다.
    """
    device_id = x_device_id or settings.DEFAULT_DEVICE_ID

    content_type = request.headers.get("content-type", "")

    try:
        if file is not None:
            image_bytes = await file.read()
        elif "multipart/form-data" in content_type:
            # FastAPI가 file 파라미터를 채우지 못한 multipart 요청 (필드명이 다른 경우 등)
            form = await request.form()
            upload = None
            for value in form.values():
                if isinstance(value, UploadFile):
                    upload = value
                    break
            if upload is None:
                return JSONResponse(
                    status_code=400,
                    content={"status": "error", "message": "multipart 요청에서 이미지 파일을 찾을 수 없습니다."},
                )
            image_bytes = await upload.read()
        else:
            image_bytes = await request.body()
    except Exception as exc:  # noqa: BLE001
        logger.error("이미지 읽기 실패: %s", exc)
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "요청 본문을 읽는 중 오류가 발생했습니다."},
        )

    if not image_bytes:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "빈 이미지입니다."},
        )

    if not _decode_check(image_bytes):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "JPEG로 decode할 수 없는 이미지입니다."},
        )

    logger.info("Image received from %s", device_id)
    logger.info("Image size: %d bytes", len(image_bytes))

    try:
        result = await _forward_to_inference(image_bytes, device_id, x_captured_at)
    except httpx.RequestError as exc:
        logger.error("inference 서비스 연결 실패: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"status": "error", "message": "inference 서비스에 연결할 수 없습니다."},
        )
    except httpx.HTTPStatusError as exc:
        logger.error("inference 서비스 오류 응답: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"status": "error", "message": "inference 서비스가 오류를 반환했습니다."},
        )

    return {
        "status": "ok",
        "device_id": device_id,
        **result,
    }
