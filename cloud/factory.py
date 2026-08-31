"""Reads CLOUD_PROVIDER from the environment and returns the matching provider.

TEAMMATE TODO: once you've implemented a real provider (see providers/remote_stub.py),
register it below under its own CLOUD_PROVIDER value (e.g. "aws_s3").
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

from cloud.base import CloudStorageProvider
from cloud.providers.local_mock import LocalMockStorageProvider

# Picks up rpi5/.env (or cloud/.env if this module is used standalone) so switching
# CLOUD_PROVIDER / Supabase keys is just editing a file, not exporting shell vars.
# Never overrides variables already set in the real environment (e.g. by Docker Compose).
load_dotenv()

_provider: CloudStorageProvider | None = None


def get_storage_provider() -> CloudStorageProvider:
    global _provider
    if _provider is not None:
        return _provider

    name = os.getenv("CLOUD_PROVIDER", "local_mock")

    if name == "local_mock":
        _provider = LocalMockStorageProvider()
    elif name == "supabase":
        from cloud.providers.supabase_provider import SupabaseStorageProvider

        _provider = SupabaseStorageProvider()
    else:
        raise ValueError(
            f"Unknown CLOUD_PROVIDER={name!r}. "
            "Implemented: 'local_mock', 'supabase'. See providers/remote_stub.py "
            "for how to add 'aws_s3' / 'gcs' / 'firebase'."
        )

    return _provider


def reset_provider_cache() -> None:
    """Clears the memoized provider so the next get_storage_provider() call re-reads
    CLOUD_PROVIDER. Only meant for tests — production code never needs to switch
    providers mid-process.
    """
    global _provider
    _provider = None
