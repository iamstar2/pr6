"""
Supabase Storage + DB 업로드를 담당하는 클라이언트 래퍼.

violation=true 인 경우에만 호출된다 (정상 이미지는 이 클래스를 거치지 않음).
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from supabase import Client, create_client

from .config import settings

logger = logging.getLogger("cloud")


class SupabaseUploader:
    def __init__(self):
        self.client: Optional[Client] = None
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            # .env가 아직 설정되지 않은 개발 초기 단계를 위해 서비스 자체는 죽이지 않는다.
            logger.warning(
                "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY가 설정되지 않았습니다. "
                "Cloud 업로드 기능이 비활성화됩니다."
            )
            return

        self.client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    @staticmethod
    def _build_storage_path() -> str:
        """violations/YYYY/MM/DD/<UUID>.jpg 형태의 경로를 생성한다."""
        now = datetime.now(timezone.utc)
        return f"{now:%Y}/{now:%m}/{now:%d}/{uuid.uuid4()}.jpg"

    def upload_violation(self, image_bytes: bytes, record: dict) -> dict:
        """
        1. Storage에 이미지 업로드
        2. DB에 storage 경로 + 메타데이터 insert

        키/토큰은 절대 로그에 남기지 않는다.
        """
        if self.client is None:
            raise RuntimeError("Supabase 클라이언트가 설정되지 않았습니다 (.env 확인 필요).")

        storage_path = self._build_storage_path()

        try:
            self.client.storage.from_(settings.SUPABASE_BUCKET).upload(
                storage_path, image_bytes, {"content-type": "image/jpeg"}
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Storage 업로드 실패: {exc}") from exc

        logger.info("Image uploaded")
        logger.info("Storage path: %s", storage_path)

        db_record = {**record, "image_path": storage_path}
        try:
            self.client.table(settings.SUPABASE_TABLE).insert(db_record).execute()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"DB insert 실패: {exc}") from exc

        logger.info("DB record inserted")
        return {"image_path": storage_path}
