"""PPE detection inference.

Real path: onnxruntime running the YOLOv8n PPE model from
https://huggingface.co/Hansung-Cho/yolov8-ppe-detection (converted to ONNX by
scripts/export_model.py — see rpi5/README.md "PC에서 개발 -> RPi5 이식" section).

Falls back to a mock/fixed response (no onnxruntime, no model file needed) when
`inference.mock: true` in config.yaml, or automatically if the ONNX file is missing,
so ①ESP32 / ④web can still be integration-tested without the model present.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

from app.config import AppConfig, get_config
from app.schemas import PPEResult

HELMET_ON = "Hardhat"
HELMET_OFF = "NO-Hardhat"
VEST_ON = "Safety Vest"
VEST_OFF = "NO-Safety Vest"
PERSON = "Person"


@dataclass
class Detection:
    class_id: int
    class_name: str
    confidence: float
    box_xywh: tuple[float, float, float, float]  # x, y, w, h — original image pixels


class _Detector:
    """Lazily-loaded onnxruntime session, shared across requests."""

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.input_w, self.input_h = cfg.model.input_size
        self.session = ort.InferenceSession(cfg.model.path, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    def _letterbox(self, img: np.ndarray) -> tuple[np.ndarray, float, tuple[int, int]]:
        h, w = img.shape[:2]
        r = min(self.input_w / w, self.input_h / h)
        new_w, new_h = round(w * r), round(h * r)
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        canvas = np.full((self.input_h, self.input_w, 3), 114, dtype=np.uint8)
        dw, dh = (self.input_w - new_w) // 2, (self.input_h - new_h) // 2
        canvas[dh:dh + new_h, dw:dw + new_w] = resized
        return canvas, r, (dw, dh)

    def _preprocess(self, img: np.ndarray) -> tuple[np.ndarray, float, tuple[int, int]]:
        canvas, ratio, pad = self._letterbox(img)
        blob = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        blob = blob.transpose(2, 0, 1)[None, ...]  # HWC -> CHW -> NCHW
        return np.ascontiguousarray(blob), ratio, pad

    def detect(self, img: np.ndarray) -> list[Detection]:
        blob, ratio, (dw, dh) = self._preprocess(img)
        raw = self.session.run(None, {self.input_name: blob})[0]  # (1, 4+num_classes, N)

        if raw.shape[1] < raw.shape[2]:
            raw = raw.transpose(0, 2, 1)  # -> (1, N, 4+num_classes)
        preds = raw[0]

        boxes_cxcywh = preds[:, :4]
        class_scores = preds[:, 4:]
        class_ids = np.argmax(class_scores, axis=1)
        confidences = class_scores[np.arange(len(class_scores)), class_ids]

        keep = confidences >= self.cfg.inference.confidence_threshold
        boxes_cxcywh, class_ids, confidences = boxes_cxcywh[keep], class_ids[keep], confidences[keep]
        if len(confidences) == 0:
            return []

        # network-input-space cx,cy,w,h -> original-image-space x,y,w,h (undo letterbox)
        cx, cy, w, h = boxes_cxcywh.T
        x = (cx - w / 2 - dw) / ratio
        y = (cy - h / 2 - dh) / ratio
        w = w / ratio
        h = h / ratio
        boxes_xywh = np.stack([x, y, w, h], axis=1)

        idxs = cv2.dnn.NMSBoxes(
            boxes_xywh.tolist(), confidences.tolist(),
            self.cfg.inference.confidence_threshold, self.cfg.inference.nms_iou_threshold,
        )
        idxs = np.array(idxs).flatten() if len(idxs) else []

        classes = self.cfg.classes
        return [
            Detection(
                class_id=int(class_ids[i]),
                class_name=classes.get(int(class_ids[i]), str(class_ids[i])),
                confidence=float(confidences[i]),
                box_xywh=tuple(float(v) for v in boxes_xywh[i]),
            )
            for i in idxs
        ]


_detector: _Detector | None = None
_mock_reason: str | None = None


def _get_detector() -> _Detector | None:
    """Returns the singleton detector, or None if mock mode is active/forced."""
    global _detector, _mock_reason
    cfg = get_config()

    if cfg.inference.mock:
        _mock_reason = "inference.mock=true in config.yaml"
        return None

    if _detector is not None:
        return _detector

    if not Path(cfg.model.path).exists():
        _mock_reason = f"model file not found at {cfg.model.path} (run scripts/export_model.py)"
        return None

    _detector = _Detector(cfg)
    return _detector


def _pick_primary_detection(dets: list[Detection]) -> Detection | None:
    persons = [d for d in dets if d.class_name == PERSON]
    if persons:
        return max(persons, key=lambda d: d.confidence)
    return max(dets, key=lambda d: d.confidence) if dets else None


def _mock_result() -> PPEResult:
    violation = random.random() < 0.5
    helmet_detected = not violation or random.random() < 0.3
    vest_detected = not violation or not helmet_detected
    return PPEResult(
        request_id="", device_id="", timestamp="",
        helmet_detected=helmet_detected,
        vest_detected=vest_detected,
        violation=(not helmet_detected) or (not vest_detected),
        confidence=round(random.uniform(0.6, 0.95), 2),
        bbox=[80.0, 60.0, 160.0, 240.0],
        image_ref="",
    )


def infer_ppe(image: np.ndarray) -> PPEResult:
    """YOLOv8 ONNX 모델로 헬멧/조끼 착용 여부 추론.

    - 사람 bbox 검출 (다수 검출 시 confidence 최고값을 대표 bbox로 사용 — 프레임당
      단일 인물을 가정한 v1 휴리스틱. 다중 인물의 개별 판정은 TODO: person<->PPE
      IoU 매칭 필요)
    - 헬멧 착용 여부(helmet_detected): 'Hardhat' 검출 O and 'NO-Hardhat' 검출 X
    - 조끼 착용 여부(vest_detected): 'Safety Vest' 검출 O and 'NO-Safety Vest' 검출 X
    - violation: bool = not helmet_detected or not vest_detected
    - 단, 'Person'이 이 프레임에서 전혀 검출되지 않으면 판정 자체를 하지 않는다(violation=False).
      ESP32의 FOMO는 오탐지가 있을 수 있고(예: 사람이 이미 프레임을 벗어남), 이 게이트가 없으면
      아무것도 안 찍힌 빈 프레임이 'Hardhat/Vest 미검출'로 해석되어 매번 위반으로 잘못 판정된다.
    - 'Person' 판정에는 일반 confidence_threshold보다 높은 person_confidence_threshold를
      쓴다 — 범용 검출기가 책상/키보드 등을 낮은 확신으로 "사람일 수도"라고 오판하는 경우까지
      막기 위해서다 (헬멧/조끼 클래스는 어차피 사람이 확실할 때만 보므로 기존 임계값 유지).
    """
    detector = _get_detector()
    if detector is None:
        result = _mock_result()
        return result

    t0 = time.time()
    dets = detector.detect(image)
    elapsed_ms = (time.time() - t0) * 1000

    class_names = {d.class_name for d in dets}
    person_threshold = detector.cfg.inference.person_confidence_threshold
    person_present = any(d.class_name == PERSON and d.confidence >= person_threshold for d in dets)
    if person_present:
        helmet_detected = HELMET_ON in class_names and HELMET_OFF not in class_names
        vest_detected = VEST_ON in class_names and VEST_OFF not in class_names
        violation = (not helmet_detected) or (not vest_detected)
    else:
        # No (confidently) person in this frame per RPi5's own model — nothing to
        # judge, so don't report a false violation regardless of what else is/isn't seen.
        helmet_detected, vest_detected, violation = True, True, False

    primary = _pick_primary_detection(dets)
    confidence = primary.confidence if primary else 0.0
    if primary:
        bbox = list(primary.box_xywh)
    else:
        h, w = image.shape[:2]
        bbox = [0.0, 0.0, float(w), float(h)]

    return PPEResult(
        request_id="", device_id="", timestamp="",
        helmet_detected=helmet_detected,
        vest_detected=vest_detected,
        violation=violation,
        confidence=round(confidence, 4),
        bbox=[round(v, 1) for v in bbox],
        image_ref=f"<in-memory, inference {elapsed_ms:.0f}ms, {len(dets)} detections>",
        detections=[
            {
                "label": d.class_name,
                "confidence": round(d.confidence, 3),
                "box": [round(v, 1) for v in d.box_xywh],
            }
            for d in dets
        ],
    )
