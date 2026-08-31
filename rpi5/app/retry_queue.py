"""On-disk retry queue for violations that failed to reach cloud storage.

Graceful degradation contract: a cloud outage must never lose evidence and must
never block the detection pipeline. routers/detect.py already fires cloud
upload off in the background (asyncio.create_task) so a slow/down cloud
backend can't stall the ESP32 response; this module is what happens when that
background upload still fails — the image + record are written to disk
immediately (so a process restart doesn't lose them either) and a background
loop (run_forever, started from app.main's startup event) retries them until
the provider accepts them.

Two bounds keep this from becoming its own disk-exhaustion problem during a
long outage: retry_queue_max_entries (evict oldest on overflow) and
retry_queue_max_age_seconds (give up on anything older, move it aside instead
of retrying forever) — see app/config.py for the numbers and rationale.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from cloud.factory import get_storage_provider
from cloud.schemas import ViolationRecord

from app.config import get_config

logger = logging.getLogger("rpi5.retry_queue")

# Expired entries are moved here instead of deleted (recoverable by a human)
# and excluded from _entries() so they're never counted or retried again.
_EXPIRED_DIRNAME = "_expired"


def _queue_dir() -> Path:
    d = Path(get_config().retry_queue_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _entry_age_seconds(entry_dir: Path) -> float:
    meta_path = entry_dir / "meta.json"
    if not meta_path.exists():
        return 0.0  # no timestamp on disk — don't expire what we can't date
    try:
        enqueued_at = json.loads(meta_path.read_text(encoding="utf-8"))["enqueued_at"]
    except (json.JSONDecodeError, KeyError, OSError):
        return 0.0
    return time.time() - enqueued_at


def _entries(queue_dir: Path) -> list[Path]:
    """Oldest first — eviction and the retry sweep both rely on this order.

    Sorted by age (meta.json's enqueued_at), NOT by directory name: entries are
    named after a random request_id UUID, so name order has no relationship to
    actual queue age.
    """
    candidates = [p for p in queue_dir.iterdir() if p.is_dir() and p.name != _EXPIRED_DIRNAME]
    return sorted(candidates, key=_entry_age_seconds, reverse=True)


def _rmtree(path: Path) -> None:
    for child in path.iterdir():
        child.unlink()
    path.rmdir()


async def enqueue(image_bytes: bytes, record: ViolationRecord) -> None:
    """Persists a violation that failed to upload, for later retry.

    Enforces retry_queue_max_entries by evicting the OLDEST entry first when
    full — a computable disk ceiling matters more than guaranteeing every
    single violation survives an unbounded outage. Eviction is logged loudly
    (it drops real evidence), never silent.
    """
    cfg = get_config()
    queue_dir = _queue_dir()

    def _prepare_and_write() -> None:
        existing = _entries(queue_dir)
        if len(existing) >= cfg.retry_queue_max_entries:
            oldest = existing[0]
            logger.warning(
                "Retry queue at capacity (%d entries) — evicting oldest queued "
                "violation %s to make room for %s. That evidence was NOT uploaded "
                "and is now gone.",
                cfg.retry_queue_max_entries, oldest.name, record.id,
            )
            _rmtree(oldest)

        entry_dir = queue_dir / record.id
        entry_dir.mkdir(parents=True, exist_ok=True)
        (entry_dir / "image.jpg").write_bytes(image_bytes)
        (entry_dir / "record.json").write_text(record.model_dump_json(), encoding="utf-8")
        (entry_dir / "meta.json").write_text(json.dumps({"enqueued_at": time.time()}), encoding="utf-8")

    await asyncio.to_thread(_prepare_and_write)
    logger.warning("Queued violation request_id=%s for retry at %s", record.id, queue_dir / record.id)


async def pending_count() -> int:
    d = _queue_dir()
    return await asyncio.to_thread(lambda: len(_entries(d)))


async def _expire(entry_dir: Path, max_age: float) -> None:
    logger.error(
        "Giving up on queued violation request_id=%s after exceeding "
        "retry_queue_max_age_seconds=%.0f — needs manual attention. Image is "
        "preserved at %s/%s, just no longer retried automatically.",
        entry_dir.name, max_age, _EXPIRED_DIRNAME, entry_dir.name,
    )

    def _move() -> None:
        expired_root = entry_dir.parent / _EXPIRED_DIRNAME
        expired_root.mkdir(parents=True, exist_ok=True)
        target = expired_root / entry_dir.name
        if not target.exists():
            entry_dir.rename(target)

    await asyncio.to_thread(_move)


async def _retry_once() -> None:
    cfg = get_config()
    provider = get_storage_provider()
    queue_dir = _queue_dir()
    entries = await asyncio.to_thread(_entries, queue_dir)

    for entry_dir in entries:
        if _entry_age_seconds(entry_dir) > cfg.retry_queue_max_age_seconds:
            await _expire(entry_dir, cfg.retry_queue_max_age_seconds)
            continue

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
        except Exception:  # noqa: BLE001 — one bad entry must not stop the sweep
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
        except Exception:  # noqa: BLE001 — the sweep loop itself must never die
            logger.exception("Retry queue sweep failed")
