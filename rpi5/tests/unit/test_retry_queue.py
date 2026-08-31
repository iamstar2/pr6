from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

from cloud.schemas import ViolationRecord

from app import config, retry_queue


def _set_age(tmp_path, request_id: str, age_seconds: float) -> None:
    """Backdates a queued entry's meta.json so age-based tests don't depend on
    real wall-clock time passing between enqueue calls."""
    meta_path = tmp_path / request_id / "meta.json"
    meta_path.write_text(json.dumps({"enqueued_at": time.time() - age_seconds}), encoding="utf-8")


def _record(request_id: str = "req-1") -> ViolationRecord:
    return ViolationRecord(
        id=request_id,
        device_id="esp32-01",
        timestamp="2026-01-01T00:00:00Z",
        helmet_detected=False,
        vest_detected=True,
        image_url="",
        violation_type="no_helmet",
    )


async def test_enqueue_persists_image_and_record(tmp_path, monkeypatch):
    monkeypatch.setenv("RETRY_QUEUE_DIR", str(tmp_path))
    config.get_config.cache_clear()

    await retry_queue.enqueue(b"jpeg-bytes", _record("req-1"))

    entry = tmp_path / "req-1"
    assert (entry / "image.jpg").read_bytes() == b"jpeg-bytes"
    assert '"id":"req-1"' in (entry / "record.json").read_text(encoding="utf-8")
    assert await retry_queue.pending_count() == 1


async def test_retry_once_removes_entry_on_success(tmp_path, monkeypatch):
    monkeypatch.setenv("RETRY_QUEUE_DIR", str(tmp_path))
    config.get_config.cache_clear()
    await retry_queue.enqueue(b"jpeg-bytes", _record("req-2"))

    fake_provider = AsyncMock()
    fake_provider.upload_image.return_value = "http://example/req-2.jpg"
    monkeypatch.setattr(retry_queue, "get_storage_provider", lambda: fake_provider)

    await retry_queue._retry_once()

    assert await retry_queue.pending_count() == 0
    fake_provider.upload_image.assert_awaited_once()
    fake_provider.save_record.assert_awaited_once()


async def test_retry_once_keeps_entry_on_repeated_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("RETRY_QUEUE_DIR", str(tmp_path))
    config.get_config.cache_clear()
    await retry_queue.enqueue(b"jpeg-bytes", _record("req-3"))

    fake_provider = AsyncMock()
    fake_provider.upload_image.side_effect = RuntimeError("cloud still down")
    monkeypatch.setattr(retry_queue, "get_storage_provider", lambda: fake_provider)

    await retry_queue._retry_once()

    assert await retry_queue.pending_count() == 1


async def test_enqueue_evicts_oldest_when_at_capacity(tmp_path, monkeypatch):
    monkeypatch.setenv("RETRY_QUEUE_DIR", str(tmp_path))
    monkeypatch.setenv("RETRY_QUEUE_MAX_ENTRIES", "2")
    config.get_config.cache_clear()

    await retry_queue.enqueue(b"a", _record("req-oldest"))
    _set_age(tmp_path, "req-oldest", age_seconds=300)
    await retry_queue.enqueue(b"b", _record("req-middle"))
    _set_age(tmp_path, "req-middle", age_seconds=100)

    # Queue is now at capacity (2/2) — this third enqueue must evict req-oldest,
    # not req-middle, even though req-middle also arrived before it.
    await retry_queue.enqueue(b"c", _record("req-newest"))

    assert await retry_queue.pending_count() == 2
    assert not (tmp_path / "req-oldest").exists()
    assert (tmp_path / "req-middle").exists()
    assert (tmp_path / "req-newest").exists()


async def test_retry_once_expires_entries_past_max_age(tmp_path, monkeypatch):
    monkeypatch.setenv("RETRY_QUEUE_DIR", str(tmp_path))
    monkeypatch.setenv("RETRY_QUEUE_MAX_AGE_SECONDS", "60")
    config.get_config.cache_clear()
    await retry_queue.enqueue(b"jpeg-bytes", _record("req-stale"))
    _set_age(tmp_path, "req-stale", age_seconds=999)

    fake_provider = AsyncMock()
    monkeypatch.setattr(retry_queue, "get_storage_provider", lambda: fake_provider)

    await retry_queue._retry_once()

    assert await retry_queue.pending_count() == 0
    assert not (tmp_path / "req-stale").exists()
    assert (tmp_path / "_expired" / "req-stale" / "image.jpg").exists()
    fake_provider.upload_image.assert_not_awaited()  # never even attempted
