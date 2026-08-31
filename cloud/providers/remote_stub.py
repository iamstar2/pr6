"""Skeleton for a real cloud provider (AWS S3 / GCP Cloud Storage / Firebase).

TEAMMATE TODO:
  1. Rename this class (e.g. S3StorageProvider, GcsStorageProvider, FirebaseStorageProvider).
  2. Fill in __init__ with the SDK client for your chosen provider, reading config
     from env vars (add them to cloud/.env.example and cloud/config.py).
  3. Implement upload_image() to actually upload and return a public/signed URL.
  4. Implement save_record() to write to your chosen DB (DynamoDB, Firestore, etc).
  5. Register the class in cloud/factory.py under CLOUD_PROVIDER="aws_s3" (or gcs/firebase).
"""
from __future__ import annotations

from cloud.base import CloudStorageProvider
from cloud.schemas import ViolationRecord


class RemoteStorageProvider(CloudStorageProvider):
    def __init__(self) -> None:
        # TODO: init AWS boto3 client / GCS client / Firebase admin SDK here,
        # using values from cloud/config.py (env-driven).
        raise NotImplementedError(
            "RemoteStorageProvider is a skeleton — implement __init__ for your provider."
        )

    async def upload_image(self, image_bytes: bytes, key: str) -> str:
        # TODO: upload image_bytes under `key` and return a publicly accessible URL.
        raise NotImplementedError

    async def save_record(self, record: ViolationRecord) -> None:
        # TODO: persist `record` (a ViolationRecord) to your metadata store.
        raise NotImplementedError
