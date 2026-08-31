"""Provider abstraction for violation storage (image + metadata).

TEAMMATE TODO: pick AWS S3 / GCP Cloud Storage / Firebase Storage+Firestore,
implement a new class in cloud/providers/ that subclasses CloudStorageProvider,
and register it in cloud/factory.py. LocalMockStorageProvider is a fully working
reference implementation you can copy the shape of.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from cloud.schemas import ViolationRecord


class CloudStorageProvider(ABC):
    @abstractmethod
    async def upload_image(self, image_bytes: bytes, key: str) -> str:
        """이미지 업로드 후 접근 가능한 URL 반환"""
        raise NotImplementedError

    @abstractmethod
    async def save_record(self, record: ViolationRecord) -> None:
        """위반 기록 메타데이터 DB 저장"""
        raise NotImplementedError
