"""
receiver 서비스 설정.

환경변수로부터 값을 읽어온다. docker-compose 실행 시 .env 파일이 주입된다.
"""
import os


class Settings:
    # inference 컨테이너의 내부 API 주소 (docker-compose 서비스명 기준)
    INFERENCE_URL: str = os.getenv("INFERENCE_URL", "http://inference:8001")

    # ESP32가 이미지를 보낼 때 device id를 명시하지 않은 경우 사용할 기본값
    DEFAULT_DEVICE_ID: str = os.getenv("DEFAULT_DEVICE_ID", "unknown-device")

    # inference 서비스 호출 타임아웃 (초)
    INFERENCE_TIMEOUT_SEC: float = float(os.getenv("INFERENCE_TIMEOUT_SEC", "10"))


settings = Settings()
