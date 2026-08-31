from __future__ import annotations

import json

import pytest
from cloud.providers.local_mock import LocalMockStorageProvider
from cloud.schemas import ViolationRecord


async def test_upload_and_save_round_trip(tmp_path):
    provider = LocalMockStorageProvider(storage_dir=str(tmp_path), public_base_url="http://x/media")

    url = await provider.upload_image(b"fake-jpeg-bytes", key="esp32-01/req-1.jpg")
    assert url == "http://x/media/esp32-01/req-1.jpg"
    assert (tmp_path / "images" / "esp32-01" / "req-1.jpg").read_bytes() == b"fake-jpeg-bytes"

    await provider.save_record(ViolationRecord(
        id="req-1", device_id="esp32-01", timestamp="2026-01-01T00:00:00Z",
        helmet_detected=False, vest_detected=True, image_url=url, violation_type="no_helmet",
    ))
    lines = (tmp_path / "records.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["id"] == "req-1"
    assert parsed["image_url"] == url


async def test_upload_image_blocks_path_traversal(tmp_path):
    provider = LocalMockStorageProvider(storage_dir=str(tmp_path), public_base_url="http://x/media")

    with pytest.raises(ValueError):
        await provider.upload_image(b"payload", key="../../outside.jpg")

    assert not (tmp_path.parent / "outside.jpg").exists()
    assert not (tmp_path.parent.parent / "outside.jpg").exists()
