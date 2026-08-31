from __future__ import annotations

import time

import pytest

from app.routers.detect import _iou, _is_same_ongoing_violation, _last_violation_by_device


def test_iou_identical_boxes_is_one():
    box = [10.0, 10.0, 50.0, 50.0]
    assert _iou(box, box) == pytest.approx(1.0)


def test_iou_disjoint_boxes_is_zero():
    assert _iou([0, 0, 10, 10], [100, 100, 10, 10]) == 0.0


def test_is_same_ongoing_violation_true_within_window_and_overlap():
    _last_violation_by_device.clear()
    _last_violation_by_device["esp32-01"] = {
        "bbox": [10.0, 10.0, 50.0, 50.0],
        "seen_at": time.monotonic(),
    }
    assert _is_same_ongoing_violation("esp32-01", [12.0, 12.0, 50.0, 50.0]) is True


def test_is_same_ongoing_violation_false_when_no_prior_record():
    _last_violation_by_device.clear()
    assert _is_same_ongoing_violation("esp32-02", [10.0, 10.0, 50.0, 50.0]) is False


def test_is_same_ongoing_violation_false_when_window_expired():
    _last_violation_by_device.clear()
    _last_violation_by_device["esp32-01"] = {
        "bbox": [10.0, 10.0, 50.0, 50.0],
        "seen_at": time.monotonic() - 999.0,
    }
    assert _is_same_ongoing_violation("esp32-01", [10.0, 10.0, 50.0, 50.0]) is False
