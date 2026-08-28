"""
YOLO 모델(best.pt 또는 best.onnx)의 class 목록을 확인하는 도구.

미착용 class 이름(NO-Hardhat 등)을 코드에서 절대 추측하지 않기 위해,
.env의 NO_HELMET_CLASSES / NO_VEST_CLASSES 값을 설정하기 전에 반드시 실행해야 한다.

실행 예시:
    python tools/inspect_model.py --weights ./best.pt
    python tools/inspect_model.py --weights ./inference/model/best.onnx
"""
import argparse
import ast
import sys
from pathlib import Path


def inspect_pt(weights: Path) -> dict[int, str]:
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit(
            "ultralytics 패키지가 필요합니다. `pip install ultralytics`로 설치하세요."
        ) from exc
    model = YOLO(str(weights))
    return dict(model.names)


def inspect_onnx(weights: Path) -> dict[int, str]:
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise SystemExit(
            "onnxruntime 패키지가 필요합니다. `pip install onnxruntime`로 설치하세요."
        ) from exc

    session = ort.InferenceSession(str(weights), providers=["CPUExecutionProvider"])
    meta = session.get_modelmeta()
    names_raw = meta.custom_metadata_map.get("names")
    if not names_raw:
        print("[WARN] ONNX metadata에 class 이름 정보(names)가 없습니다.")
        return {}
    parsed = ast.literal_eval(names_raw)
    return {int(k): str(v) for k, v in parsed.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="YOLO 모델의 class 목록 확인")
    parser.add_argument("--weights", type=str, required=True, help="best.pt 또는 best.onnx 경로")
    args = parser.parse_args()

    weights_path = Path(args.weights)
    if not weights_path.exists():
        print(f"[ERROR] 파일을 찾을 수 없습니다: {weights_path}")
        sys.exit(1)

    if weights_path.suffix == ".pt":
        names = inspect_pt(weights_path)
    elif weights_path.suffix == ".onnx":
        names = inspect_onnx(weights_path)
    else:
        print("[ERROR] .pt 또는 .onnx 파일만 지원합니다.")
        sys.exit(1)

    if not names:
        print("[ERROR] class 이름을 확인할 수 없습니다.")
        sys.exit(1)

    print("사용 가능한 class 목록:")
    for idx in sorted(names):
        print(f"  {idx}: {names[idx]}")

    print()
    print("주의: 위 이름이 .env의 NO_HELMET_CLASSES / NO_VEST_CLASSES 값과")
    print("실제로 일치하는지 반드시 확인 후 .env를 수정하세요 (대소문자/공백은 자동 처리됨).")


if __name__ == "__main__":
    main()
