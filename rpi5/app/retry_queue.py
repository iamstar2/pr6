"""On-disk retry queue for violations that failed to reach cloud storage.

Graceful degradation contract: a cloud outage must never lose evidence and must
never block the detection pipeline. routers/detect.py already fires cloud
upload off in the background (asyncio.create_task) so a slow/down cloud
backend can't stall the ESP32 response; this module is what happens when that
background upload still fails — the image + record are written to disk
immediately (so a process restart doesn't lose them either) and a background
loop (run_forever, started from app.main's startup event) retries them until
the provider accepts them.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from cloud.factory import get_storage_provider
from cloud.schemas import ViolationRecord

from app.config import get_config

logger = logging.getLogger("rpi5.retry_queue")


def _queue_dir() -> Path:
    d = Path(get_config().retry_queue_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


async def enqueue(image_bytes: bytes, record: ViolationRecord) -> None:
    """Persists a violation that failed to upload, for later retry."""
    entry_dir = _queue_dir() / record.id

    def _write() -> None:
        entry_dir.mkdir(parents=True, exist_ok=True)
        (entry_dir / "image.jpg").write_bytes(image_bytes)
        (entry_dir / "record.json").write_text(record.model_dump_json(), encoding="utf-8")

    await asyncio.to_thread(_write)
    logger.warning("Queued violation request_id=%s for retry at %s", record.id, entry_dir)


def _rmtree(path: Path) -> None:
    for child in path.iterdir():
        child.unlink()
    path.rmdir()


async def pending_count() -> int:
    d = _queue_dir()
    return await asyncio.to_thread(lambda: sum(1 for p in d.iterdir() if p.is_dir()))


async def _retry_once() -> None:
    provider = get_storage_provider()
    queue_dir = _queue_dir()
    entries = await asyncio.to_thread(lambda: sorted(p for p in queue_dir.iterdir() if p.is_dir()))

    for entry_dir in entries:
        image_path, record_path = entry_dir / "image.jpg", entry_dir / "record.json"
        if not image_path.exists() or not record_path.exists():
            continue
        try:
            record = ViolationRecord.model_validate_json(
                await asyncio.to_thread(record_path.read_text, encoding="utf-8")
            )
            image_bytes = await asyncio.to_thread(image_path.read_bytes)
            image_url = await provider.upload_image(image_bytes, key=f"{record.device_id}/{record.id}.jpg")
            await provider.save_record(record.model_copy(update={"image_url": image_url}))
        except Exception:
            logger.exception("Retry still failing for queued request_id=%s", entry_dir.name)
            continue
        await asyncio.to_thread(_rmtree, entry_dir)
        logger.info("Retry succeeded for request_id=%s, removed from queue", entry_dir.name)


async def run_forever() -> None:
    interval = get_config().retry_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            await _retry_once()
        except Exception:
            logger.exception("Retry queue sweep failed")
