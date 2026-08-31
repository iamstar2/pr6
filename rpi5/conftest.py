"""Pytest bootstrap: makes both `app` (rpi5/) and `cloud` (repo root) importable,
matching the layout the Dockerfile creates at /app (see rpi5/Dockerfile) and what
`PYTHONPATH=.. uvicorn app.main:app` gives you for local dev (see rpi5/README.md).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RPI5_ROOT = Path(__file__).resolve().parent
REPO_ROOT = RPI5_ROOT.parent

for _p in (RPI5_ROOT, REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("RPI5_CONFIG_PATH", str(RPI5_ROOT / "config.yaml"))

import pytest


@pytest.fixture(autouse=True)
def _reset_config_cache(monkeypatch):
    """get_config() is @lru_cache'd and cloud.factory's provider is a module-global
    singleton — both cache whatever CLOUD_PROVIDER/etc. was read on their *first*
    call for the rest of the process. Reset both before AND after every test so:
      (a) tests that change env vars don't leak into other tests, and
      (b) tests never accidentally hit the real CLOUD_PROVIDER=supabase from
          rpi5/.env — a test run WILL otherwise make real network calls against
          whatever Supabase project happens to be configured there. Every test
          gets local_mock by default; override CLOUD_PROVIDER explicitly (with
          get_storage_provider mocked, see tests/unit/test_retry_queue.py) if a
          test specifically needs to exercise the Supabase path.
    """
    from app import config
    from cloud import factory

    monkeypatch.setenv("CLOUD_PROVIDER", "local_mock")
    config.get_config.cache_clear()
    factory.reset_provider_cache()
    yield
    config.get_config.cache_clear()
    factory.reset_provider_cache()
