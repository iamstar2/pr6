"""
cloud 서비스 설정.

Supabase 접속 정보는 반드시 환경변수로만 주입한다 (코드에 하드코딩 금지).
"""
import os


class Settings:
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_BUCKET: str = os.getenv("SUPABASE_BUCKET", "violations")
    SUPABASE_TABLE: str = os.getenv("SUPABASE_TABLE", "violations")

    MODEL_NAME: str = os.getenv("MODEL_NAME", "PPE-YOLO")
    MODEL_VERSION: str = os.getenv("MODEL_VERSION", "1.0")


settings = Settings()
