"""Loads config.yaml + environment variables for the detection server."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

# Loaded here (not just in cloud/factory.py) so every environment-driven field
# below sees rpi5/.env even when app.config is the very first module imported
# (app.main imports it before app.routers.detect, which is what used to trigger
# cloud.factory's load_dotenv()). Never overrides a var already set in the real
# environment (e.g. Docker Compose's env_file:).
load_dotenv()

CONFIG_PATH = Path(os.getenv("RPI5_CONFIG_PATH", "./config.yaml"))


class ModelConfig(BaseModel):
    path: str
    input_size: tuple[int, int]


class InferenceConfig(BaseModel):
    mock: bool = False
    confidence_threshold: float = 0.4
    nms_iou_threshold: float = 0.45
    person_confidence_threshold: float = 0.65


class AppConfig(BaseModel):
    model: ModelConfig
    classes: dict[int, str]
    inference: InferenceConfig

    # ---- environment-driven settings (not in config.yaml on purpose: differ per deploy) ----
    host: str = "0.0.0.0"
    port: int = 8000
    public_base_url: str = "http://localhost:8000"
    web_backend_url: str = "http://localhost:4000"

    # ---- security ----
    # Shared secret ESP32 must send as X-API-Key. Empty = auth disabled (dev only).
    device_api_key: str = ""
    max_upload_bytes: int = 5 * 1024 * 1024
    # Shared secret THIS server sends as X-Internal-Token to the web backend's
    # /api/events/* — must match the web backend's own INGRESS_TOKEN. Empty = no
    # header sent (fine if the web backend's INGRESS_TOKEN is also unset).
    web_ingress_token: str = ""

    # ---- reliability (graceful degradation) ----
    # Violations that fail to reach cloud storage are persisted here and retried
    # in the background instead of being lost. Holds real photos — gitignored.
    retry_queue_dir: str = "./data/retry_queue"
    retry_interval_seconds: float = 30.0
    # Hard cap on queued entries — without one, a prolonged cloud outage fills the
    # disk. Oldest entry is evicted (logged, not silent) to make room for a new
    # one. Rough disk ceiling = retry_queue_max_entries * a VGA JPEG (~150-300KB),
    # so 200 * 300KB ≈ 60MB at the default.
    retry_queue_max_entries: int = 200
    # An entry older than this is given up on (moved to <retry_queue_dir>/_expired/
    # instead of retried forever) and logged as ERROR — a cloud outage this long
    # needs a human, not an infinite retry loop. Default 24h.
    retry_queue_max_age_seconds: float = 24 * 60 * 60
    web_event_max_retries: int = 3
    web_event_backoff_base_seconds: float = 0.5

    # ---- environment profile / logging ----
    env: str = "development"  # development | staging | production
    log_level: str = ""       # blank -> derived from `env`, see logging_config.py
    log_dir: str = "./logs"
    # Optional: also POST every log line to a central log collector (Loki/ELK/CloudWatch
    # ingest endpoint, ...). Blank = console + local rotating file only.
    log_ship_url: str = ""


def _env_overrides() -> dict:
    """Reads every environment-driven field above fresh from os.environ.

    Deliberately a function, not Pydantic field defaults (`= os.getenv(...)`)  —
    a field default is evaluated once, when this module is first imported, so it
    can't see a `.env` value that loads later or an env var a test sets after
    the fact. Reading it here means calling get_config.cache_clear() after
    changing the environment actually takes effect (see rpi5/tests/).
    """
    return {
        "host": os.getenv("HOST", "0.0.0.0"),
        "port": int(os.getenv("PORT", "8000")),
        "public_base_url": os.getenv("PUBLIC_BASE_URL", "http://localhost:8000"),
        "web_backend_url": os.getenv("WEB_BACKEND_URL", "http://localhost:4000"),
        "device_api_key": os.getenv("DEVICE_API_KEY", ""),
        "max_upload_bytes": int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024))),
        "web_ingress_token": os.getenv("WEB_INGRESS_TOKEN", ""),
        "retry_queue_dir": os.getenv("RETRY_QUEUE_DIR", "./data/retry_queue"),
        "retry_interval_seconds": float(os.getenv("RETRY_INTERVAL_SECONDS", "30")),
        "retry_queue_max_entries": int(os.getenv("RETRY_QUEUE_MAX_ENTRIES", "200")),
        "retry_queue_max_age_seconds": float(os.getenv("RETRY_QUEUE_MAX_AGE_SECONDS", str(24 * 60 * 60))),
        "web_event_max_retries": int(os.getenv("WEB_EVENT_MAX_RETRIES", "3")),
        "web_event_backoff_base_seconds": float(os.getenv("WEB_EVENT_BACKOFF_BASE_S", "0.5")),
        "env": os.getenv("ENV", "development"),
        "log_level": os.getenv("LOG_LEVEL", ""),
        "log_dir": os.getenv("LOG_DIR", "./logs"),
        "log_ship_url": os.getenv("LOG_SHIP_URL", ""),
    }


@lru_cache
def get_config() -> AppConfig:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return AppConfig(**raw, **_env_overrides())
