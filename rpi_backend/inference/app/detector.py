"""
PPE(안전모/안전조끼) 미착용 판정 핵심 로직.

YOLO ONNX 모델을 이용해 detection을 수행하고,
환경변수로 지정된 미착용 class 이름과 비교하여 violation 여부를 결정한다.
"""
import logging
import time
from typing import Optional

import cv2
import numpy as np

from .config import settings
from .postprocess import decode_image, preprocess, postprocess
from .yolo_onnx import YoloOnnxModel

logger = logging.getLogger("inference")

VIOLATION_NO_HARDHAT = "NO_HARDHAT"
VIOLATION_NO_SAFETY_VEST = "NO_SAFETY_VEST"


def _normalize(name: str) -> str:
    """class 이름 비교를 위해 소문자 + trim 처리한다."""
    return name.strip().lower()


class PPEDetector:
    def __init__(self):
        self.model = YoloOnnxModel(settings.MODEL_PATH)
        self._no_helmet_names = {_normalize(n) for n in settings.NO_HELMET_CLASSES}
        self._no_vest_names = {_normalize(n) for n in settings.NO_VEST_CLASSES}
        self._warn_if_no_explicit_violation_classes()

    def _warn_if_no_explicit_violation_classes(self) -> None:
        """
        모델에 Person/Hardhat/Safety Vest 같은 '착용' class만 있고
        명시적인 미착용 class가 없다면, class 부재만으로 미착용을 단정하지 않도록 경고한다.
        """
        model_names = {_normalize(n) for n in self.model.class_names.values()}
        has_no_helmet = bool(model_names & self._no_helmet_names)
        has_no_vest = bool(model_names & self._no_vest_names)
        if not has_no_helmet and not has_no_vest:
            logger.warning(
                "현재 모델에는 명시적인 미착용 class가 없어 "
                "추가 PPE-person association 로직 또는 미착용 class 학습 모델이 필요합니다."
            )

    def _classify(self, class_name: str) -> Optional[str]:
        normalized = _normalize(class_name)
        if normalized in self._no_helmet_names:
            return VIOLATION_NO_HARDHAT
        if normalized in self._no_vest_names:
            return VIOLATION_NO_SAFETY_VEST
        return None

    def detect(self, image_bytes: bytes) -> dict:
        image = decode_image(image_bytes)
        if image is None:
            raise ValueError("JPEG 이미지를 decode할 수 없습니다.")

        input_tensor, letterbox = preprocess(image, settings.INPUT_SIZE)

        start = time.perf_counter()
        raw_output = self.model.infer(input_tensor)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("Inference time: %.0f ms", elapsed_ms)

        raw_detections = postprocess(
            raw_output,
            letterbox,
            orig_shape=image.shape[:2],
            conf_threshold=settings.CONFIDENCE_THRESHOLD,
            iou_threshold=settings.IOU_THRESHOLD,
        )
        logger.info("Detection count: %d", len(raw_detections))

        detections: list[dict] = []
        violation_types: set[str] = set()

        for det in raw_detections:
            class_name = self.model.class_names.get(det.class_id, f"class_{det.class_id}")
            violation_type = self._classify(class_name)
            detections.append(
                {
                    "class_name": class_name,
                    "violation_type": violation_type,
                    "confidence": round(det.confidence, 4),
                    "bbox": {
                        "x1": round(det.x1),
                        "y1": round(det.y1),
                        "x2": round(det.x2),
                        "y2": round(det.y2),
                    },
                }
            )
            if violation_type:
                violation_types.add(violation_type)

        violation = len(violation_types) > 0
        if violation:
            logger.info("Violation: %s", ", ".join(sorted(violation_types)))

        annotated_image: Optional[bytes] = None
        if violation:
            annotated_image = self._draw_violation_boxes(image, detections)

        return {
            "violation": violation,
            "violation_types": sorted(violation_types),
            "detections": detections,
            "annotated_image": annotated_image,
        }

    @staticmethod
    def _draw_violation_boxes(image: np.ndarray, detections: list[dict]) -> bytes:
        """미착용으로 판정된 detection에 한해 bbox와 class/confidence 라벨을 그린다."""
        annotated = image.copy()
        for det in detections:
            if det["violation_type"] is None:
                continue
            bbox = det["bbox"]
            x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
            label = f"{det['class_name'].upper()} {det['confidence']:.2f}"

            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)
            (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            label_y = max(y1, text_h + 8)
            cv2.rectangle(
                annotated,
                (x1, label_y - text_h - 8),
                (x1 + text_w + 4, label_y),
                (0, 0, 255),
                -1,
            )
            cv2.putText(
                annotated,
                label,
                (x1 + 2, label_y - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )

        success, buffer = cv2.imencode(".jpg", annotated)
        if not success:
            raise RuntimeError("위반 이미지 인코딩에 실패했습니다.")
        return buffer.tobytes()


class CooldownTracker:
    """
    device_id + violation_types 조합 기준으로 cooldown 시간 내 재업로드를 막는다.
    프로세스 메모리 내에서만 유지되는 단순 캐시이다 (재시작 시 초기화됨).
    """

    def __init__(self, cooldown_sec: float):
        self._cooldown_sec = cooldown_sec
        self._last_upload_at: dict[tuple, float] = {}

    def is_cooling_down(self, key: tuple) -> bool:
        last = self._last_upload_at.get(key)
        if last is None:
            return False
        return (time.time() - last) < self._cooldown_sec

    def mark_uploaded(self, key: tuple) -> None:
        self._last_upload_at[key] = time.time()
