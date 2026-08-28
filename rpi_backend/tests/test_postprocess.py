"""
YOLO ONNX 후처리 로직(postprocess.py) 단위 테스트.
실제 ONNX 모델 없이, Ultralytics 스타일(4+num_classes, num_boxes) 형태의
가짜 raw output 배열만으로 검증한다.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

INFERENCE_ROOT = Path(__file__).resolve().parents[1] / "inference"


def _load_postprocess_module():
    """다른 테스트 파일이 캐싱한 'app' 패키지와 충돌하지 않도록 매번 새로 로드한다."""
    sys.path.insert(0, str(INFERENCE_ROOT))
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    import app.postprocess as postprocess

    return postprocess


postprocess = _load_postprocess_module()


def _make_raw_output(boxes: list[tuple[float, float, float, float, list[float]]]) -> np.ndarray:
    """
    boxes: [(cx, cy, w, h, [class_score, ...]), ...]
    Ultralytics 스타일 (1, 4+num_classes, num_boxes) 배열로 변환한다.
    """
    num_classes = len(boxes[0][4])
    num_boxes = len(boxes)
    output = np.zeros((4 + num_classes, num_boxes), dtype=np.float32)
    for i, (cx, cy, w, h, scores) in enumerate(boxes):
        output[0, i] = cx
        output[1, i] = cy
        output[2, i] = w
        output[3, i] = h
        output[4:, i] = scores
    return output[np.newaxis, ...]  # (1, 4+num_classes, num_boxes)


def test_postprocess_filters_low_confidence():
    # 2개 class(Hardhat=0, NO-Hardhat=1), 여러 box 중 1개만 threshold를 넘긴다.
    boxes = [
        (100, 100, 50, 50, [0.10, 0.05]),  # 낮은 confidence -> 제거되어야 함
        (200, 200, 60, 80, [0.05, 0.90]),  # NO-Hardhat, 높은 confidence
    ]
    # transpose 로직이 제대로 동작하도록 box 개수를 채널 수보다 많게 둔다.
    boxes = boxes * 5  # 10 boxes, 4+2=6 channels -> channels(6) < boxes(10)
    raw_output = _make_raw_output(boxes)

    letterbox = postprocess.Letterbox(ratio=1.0, pad_x=0, pad_y=0)
    detections = postprocess.postprocess(
        raw_output,
        letterbox,
        orig_shape=(480, 640),
        conf_threshold=0.4,
        iou_threshold=0.45,
    )

    assert len(detections) >= 1
    assert all(det.confidence >= 0.4 for det in detections)
    assert all(det.class_id == 1 for det in detections)


def test_letterbox_resize_keeps_aspect_ratio():
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    resized, lb = postprocess.letterbox_resize(image, target_size=640)

    assert resized.shape == (640, 640, 3)
    assert lb.ratio == pytest.approx(640 / 640)


def test_preprocess_output_shape():
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    tensor, _ = postprocess.preprocess(image, target_size=640)

    assert tensor.shape == (1, 3, 640, 640)
    assert tensor.dtype == np.float32
    assert tensor.max() <= 1.0


def test_decode_image_invalid_bytes_returns_none():
    assert postprocess.decode_image(b"not an image") is None
