"""
inference 서비스 설정.

미착용 class 이름은 절대 코드에 하드코딩하지 않고 환경변수로 주입받는다.
실제 모델의 class 이름은 tools/inspect_model.py 로 먼저 확인해야 한다.
"""
import os


def _split_env_list(raw: str) -> list[str]:
    """쉼표로 구분된 환경변수 값을 리스트로 변환한다. 앞뒤 공백은 제거한다."""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    MODEL_PATH: str = os.getenv("MODEL_PATH", "/app/model/best.onnx")

    CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.40"))
    IOU_THRESHOLD: float = float(os.getenv("IOU_THRESHOLD", "0.45"))

    # YOLO 입력 이미지 크기 (export_onnx.py의 imgsz와 반드시 일치해야 함)
    INPUT_SIZE: int = int(os.getenv("INPUT_SIZE", "640"))

    # 미착용으로 판정할 class 이름 후보 목록 (모델마다 이름이 다를 수 있어 여러 개 등록 가능)
    NO_HELMET_CLASSES: list[str] = _split_env_list(
        os.getenv("NO_HELMET_CLASSES", "NO-Hardhat,no_helmet,without_helmet")
    )
    NO_VEST_CLASSES: list[str] = _split_env_list(
        os.getenv("NO_VEST_CLASSES", "NO-Safety Vest,no_vest,without_vest")
    )

    # 사람으로 인식할 class 이름 후보. violation은 사람이 감지된 경우에만 판정한다
    # (사람 없이 방치된 안전모/조끼 물체만으로는 미착용 판정을 하지 않기 위함).
    PERSON_CLASSES: list[str] = _split_env_list(os.getenv("PERSON_CLASSES", "Person,person"))

    # violation 발생 시에만 호출되는 cloud 서비스 내부 주소
    CLOUD_URL: str = os.getenv("CLOUD_URL", "http://cloud:8002")
    CLOUD_TIMEOUT_SEC: float = float(os.getenv("CLOUD_TIMEOUT_SEC", "10"))

    # 같은 device_id + violation_types 조합의 재업로드를 막는 cooldown (초)
    EVENT_COOLDOWN_SEC: float = float(os.getenv("EVENT_COOLDOWN_SEC", "5"))

    MODEL_NAME: str = os.getenv("MODEL_NAME", "PPE-YOLO")
    MODEL_VERSION: str = os.getenv("MODEL_VERSION", "1.0")


settings = Settings()
