"""Supabase-backed cloud storage provider (Storage for images, a Postgres table for
metadata). This is the real provider used once CLOUD_PROVIDER=supabase.

Setup (see cloud/README.md for the full walkthrough):
  1. Create a Supabase project.
  2. Storage -> New bucket -> name it (default expected: "violations"), make it Public
     (simplest — this provider calls get_public_url()). For a private bucket, switch
     upload_image() below to create_signed_url() instead.
  3. SQL editor -> run cloud/supabase_schema.sql to create the metadata table.
  4. Project Settings -> API -> copy the Project URL and a key into rpi5/.env
     (SUPABASE_URL, SUPABASE_KEY — service_role key recommended so inserts aren't
     blocked by Row Level Security; never expose that key to a browser/client).
"""
from __future__ import annotations

import asyncio
import os

from supabase import Client, create_client

from cloud.base import CloudStorageProvider
from cloud.schemas import ViolationRecord


class SupabaseStorageProvider(CloudStorageProvider):
    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        bucket: str | None = None,
        table: str | None = None,
    ) -> None:
        self.url = url or os.getenv("SUPABASE_URL")
        self.key = key or os.getenv("SUPABASE_KEY")
        self.bucket = bucket or os.getenv("SUPABASE_BUCKET", "violations")
        self.table = table or os.getenv("SUPABASE_TABLE", "violation_records")

        if not self.url or not self.key:
            raise ValueError(
                "SUPABASE_URL / SUPABASE_KEY are not set. Copy rpi5/.env.example to "
                "rpi5/.env, fill them in, and set CLOUD_PROVIDER=supabase."
            )

        self.client: Client = create_client(self.url, self.key)

    async def upload_image(self, image_bytes: bytes, key: str) -> str:
        def _upload() -> str:
            self.client.storage.from_(self.bucket).upload(
                path=key,
                file=image_bytes,
                file_options={"content-type": "image/jpeg", "upsert": "true"},
            )
            return self.client.storage.from_(self.bucket).get_public_url(key)

        return await asyncio.to_thread(_upload)

    async def save_record(self, record: ViolationRecord) -> None:
        def _insert() -> None:
            self.client.table(self.table).insert(record.model_dump()).execute()

        await asyncio.to_thread(_insert)
