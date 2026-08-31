"""Local filesystem mock of a cloud storage provider.

Lets ①ESP32 and ④웹 대시보드 be integration-tested end-to-end without any real
cloud account. Images are written to disk under CLOUD_MOCK_STORAGE_DIR and served
by the RPi5 FastAPI app as static files (see rpi5/app/main.py), so the URL this
returns is directly browsable.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from cloud.base import CloudStorageProvider
from cloud.schemas import ViolationRecord


class LocalMockStorageProvider(CloudStorageProvider):
    def __init__(
        self,
        storage_dir: str | None = None,
        public_base_url: str | None = None,
    ) -> None:
        self.storage_dir = Path(
            storage_dir or os.getenv("CLOUD_MOCK_STORAGE_DIR", "./cloud/_mock_storage")
        )
        self.public_base_url = (
            public_base_url
            or os.getenv("CLOUD_MOCK_PUBLIC_BASE_URL", "http://localhost:8000/mock-media")
        ).rstrip("/")

        self.images_dir = self.storage_dir / "images"
        self.records_path = self.storage_dir / "records.jsonl"
        self.images_dir.mkdir(parents=True, exist_ok=True)

    async def upload_image(self, image_bytes: bytes, key: str) -> str:
        def _write() -> str:
            base = self.images_dir.resolve()
            dest = (self.images_dir / key).resolve()
            # Defense in depth: the real validation is device_id whitelisting at the
            # API boundary (app/security.py), but a caller-controlled `key` landing
            # straight in a filesystem join is a path-traversal footgun regardless of
            # where it's called from — refuse to ever write outside images_dir.
            if dest != base and base not in dest.parents:
                raise ValueError(f"Refusing to write image outside images_dir: key={key!r}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(image_bytes)
            return f"{self.public_base_url}/{key}"

        return await asyncio.to_thread(_write)

    async def save_record(self, record: ViolationRecord) -> None:
        def _append() -> None:
            with self.records_path.open("a", encoding="utf-8") as f:
                f.write(record.model_dump_json() + "\n")

        await asyncio.to_thread(_append)
