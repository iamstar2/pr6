from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import retry_queue
from app.config import get_config
from app.logging_config import configure_logging
from app.routers.detect import router as detect_router

configure_logging()
logger = logging.getLogger("rpi5.main")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    cfg = get_config()
    if not cfg.device_api_key:
        logger.warning(
            "DEVICE_API_KEY is not set - /api/v1/detect is accepting UNAUTHENTICATED "
            "requests. Fine for local dev on a trusted LAN, never for anything reachable "
            "from outside it."
        )
    retry_task = asyncio.create_task(retry_queue.run_forever())
    try:
        yield
    finally:
        retry_task.cancel()


app = FastAPI(title="PPE Detection Server (RPi5 module, running on PC for now)", lifespan=_lifespan)
app.include_router(detect_router)

# Serves images written by cloud.providers.local_mock.LocalMockStorageProvider so their
# returned URLs (CLOUD_MOCK_PUBLIC_BASE_URL) are actually browsable during mock testing.
_mock_storage_dir = Path(os.getenv("CLOUD_MOCK_STORAGE_DIR", "./cloud/_mock_storage")) / "images"
_mock_storage_dir.mkdir(parents=True, exist_ok=True)
app.mount("/mock-media", StaticFiles(directory=str(_mock_storage_dir)), name="mock-media")


@app.get("/health")
async def health() -> dict:
    cfg = get_config()
    return {
        "status": "ok",
        "mock_mode": cfg.inference.mock,
        "model_path": cfg.model.path,
        "model_file_exists": Path(cfg.model.path).exists(),
        "auth_enabled": bool(cfg.device_api_key),
        "pending_retry_uploads": await retry_queue.pending_count(),
    }
