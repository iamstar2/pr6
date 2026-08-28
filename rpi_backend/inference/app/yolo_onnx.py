"""
ONNX Runtime을 이용해 YOLO 모델을 로드하고 raw inference를 수행하는 래퍼.

주의:
- Raspberry Pi 컨테이너에는 torch를 설치하지 않는다. best.onnx만 사용한다.
- 모델의 class 이름은 절대 하드코딩하지 않고, ONNX metadata에서 읽어온다.
  (Ultralytics export 시 metadata_props에 "names" 키로 저장됨)
"""
import ast
import logging
from typing import Optional

import numpy as np
import onnxruntime as ort

logger = logging.getLogger("inference")


class YoloOnnxModel:
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.session: Optional[ort.InferenceSession] = None
        self.class_names: dict[int, str] = {}
        self.input_name: str = ""

        self._load()

    def _load(self) -> None:
        try:
            self.session = ort.InferenceSession(
                self.model_path, providers=["CPUExecutionProvider"]
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"ONNX 모델을 로드할 수 없습니다 ({self.model_path}): {exc}") from exc

        self.input_name = self.session.get_inputs()[0].name
        self.class_names = self._extract_class_names()
        logger.info("Model loaded: %s", self.model_path)
        logger.info("Model classes: %s", self.class_names)

    def _extract_class_names(self) -> dict[int, str]:
        """
        Ultralytics가 export한 ONNX 모델의 metadata_props에서 class 이름을 읽어온다.
        예: {'names': "{0: 'Hardhat', 1: 'NO-Hardhat', ...}"}

        metadata가 없거나 파싱에 실패하면 빈 dict를 반환하고,
        호출부(detector)에서 class index만으로는 미착용 판정을 할 수 없다는 것을 인지해야 한다.
        """
        try:
            meta = self.session.get_modelmeta()
            names_raw = meta.custom_metadata_map.get("names")
            if not names_raw:
                logger.warning("ONNX metadata에 class 이름 정보(names)가 없습니다.")
                return {}
            parsed = ast.literal_eval(names_raw)
            return {int(k): str(v) for k, v in parsed.items()}
        except Exception as exc:  # noqa: BLE001
            logger.warning("ONNX metadata에서 class 이름을 파싱하지 못했습니다: %s", exc)
            return {}

    def infer(self, input_tensor: np.ndarray) -> np.ndarray:
        """전처리된 NCHW float32 텐서를 받아 raw output을 반환한다."""
        if self.session is None:
            raise RuntimeError("모델이 로드되지 않았습니다.")
        outputs = self.session.run(None, {self.input_name: input_tensor})
        return outputs[0]
