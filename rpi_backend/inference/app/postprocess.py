"""
YOLO ONNX 추론을 위한 전처리 / 후처리 함수 모음.

전처리: JPEG decode -> letterbox resize -> BGR->RGB -> normalize -> NCHW
후처리: confidence threshold -> NMS -> bbox를 원본 이미지 좌표로 복원
"""
from typing import NamedTuple

import cv2
import numpy as np


class Letterbox(NamedTuple):
    ratio: float
    pad_x: float
    pad_y: float


class Detection(NamedTuple):
    class_id: int
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float


def decode_image(image_bytes: bytes) -> np.ndarray | None:
    """JPEG bytes를 BGR numpy 배열로 decode한다. 실패 시 None을 반환한다."""
    np_arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    return image


def letterbox_resize(
    image: np.ndarray, target_size: int
) -> tuple[np.ndarray, Letterbox]:
    """
    가로세로 비율을 유지한 채 target_size x target_size로 맞추고
    남는 영역은 회색(114)으로 padding한다 (YOLO 표준 letterbox 방식).
    """
    h, w = image.shape[:2]
    ratio = min(target_size / h, target_size / w)
    new_w, new_h = int(round(w * ratio)), int(round(h * ratio))

    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    pad_w = target_size - new_w
    pad_h = target_size - new_h
    top, bottom = pad_h // 2, pad_h - pad_h // 2
    left, right = pad_w // 2, pad_w - pad_w // 2

    padded = cv2.copyMakeBorder(
        resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114)
    )
    return padded, Letterbox(ratio=ratio, pad_x=left, pad_y=top)


def preprocess(image: np.ndarray, target_size: int) -> tuple[np.ndarray, Letterbox]:
    """decode된 BGR 이미지를 모델 입력 텐서(NCHW, float32, 0~1)로 변환한다."""
    padded, lb = letterbox_resize(image, target_size)
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    normalized = rgb.astype(np.float32) / 255.0
    chw = normalized.transpose(2, 0, 1)  # HWC -> CHW
    nchw = np.expand_dims(chw, axis=0)
    return np.ascontiguousarray(nchw), lb


def _xywh_to_xyxy(boxes: np.ndarray) -> np.ndarray:
    xyxy = np.empty_like(boxes)
    xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
    xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
    xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
    xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
    return xyxy


def _parse_raw_output(raw_output: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Ultralytics YOLO(v8/v11 계열, export_onnx.py로 생성된 모델) ONNX 출력 형식을 파싱한다.

    출력 shape: (1, 4 + num_classes, num_boxes) - objectness 없이 class score만 존재.

    반환값: (xywh boxes, class_id, confidence) - 모두 1차원/2차원 numpy 배열
    """
    output = raw_output
    if output.ndim == 3:
        output = output[0]

    # 채널(4+num_classes)이 앞쪽 축, box 개수가 뒤쪽 축에 온다.
    # 채널 수가 box 개수보다 훨씬 적은 것이 일반적이므로 shape[0] < shape[1]이면 transpose.
    if output.shape[0] < output.shape[1]:
        output = output.T  # (num_boxes, 4+num_classes)

    boxes_xywh = output[:, 0:4]
    class_scores = output[:, 4:]
    class_id = np.argmax(class_scores, axis=1)
    confidence = class_scores[np.arange(len(class_scores)), class_id]

    return boxes_xywh, class_id, confidence


def postprocess(
    raw_output: np.ndarray,
    letterbox: Letterbox,
    orig_shape: tuple[int, int],
    conf_threshold: float,
    iou_threshold: float,
) -> list[Detection]:
    """confidence threshold + NMS + 좌표 복원까지 수행한다."""
    boxes_xywh, class_ids, confidences = _parse_raw_output(raw_output)

    mask = confidences >= conf_threshold
    if not np.any(mask):
        return []

    boxes_xywh = boxes_xywh[mask]
    class_ids = class_ids[mask]
    confidences = confidences[mask]

    boxes_xyxy = _xywh_to_xyxy(boxes_xywh)

    # cv2.dnn.NMSBoxes는 [x, y, w, h] 형식을 기대한다.
    nms_boxes = [
        [float(x1), float(y1), float(x2 - x1), float(y2 - y1)]
        for x1, y1, x2, y2 in boxes_xyxy
    ]
    indices = cv2.dnn.NMSBoxes(
        nms_boxes, confidences.tolist(), conf_threshold, iou_threshold
    )
    if len(indices) == 0:
        return []
    indices = np.array(indices).flatten()

    orig_h, orig_w = orig_shape
    detections: list[Detection] = []
    for i in indices:
        x1, y1, x2, y2 = boxes_xyxy[i]

        # letterbox padding 제거 후 원본 스케일로 복원
        x1 = (x1 - letterbox.pad_x) / letterbox.ratio
        y1 = (y1 - letterbox.pad_y) / letterbox.ratio
        x2 = (x2 - letterbox.pad_x) / letterbox.ratio
        y2 = (y2 - letterbox.pad_y) / letterbox.ratio

        x1 = float(np.clip(x1, 0, orig_w))
        y1 = float(np.clip(y1, 0, orig_h))
        x2 = float(np.clip(x2, 0, orig_w))
        y2 = float(np.clip(y2, 0, orig_h))

        detections.append(
            Detection(
                class_id=int(class_ids[i]),
                confidence=float(confidences[i]),
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
            )
        )
    return detections
