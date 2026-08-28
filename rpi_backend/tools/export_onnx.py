"""
best.pt (Ultralytics YOLO PyTorch 가중치) -> best.onnx 변환 도구.

이 스크립트에서만 ultralytics/torch 사용을 허용한다.
Raspberry Pi에서 실제로 구동되는 inference 컨테이너에는 torch를 설치하지 않는다
(무겁고, Raspberry Pi 5에서는 onnxruntime만으로 충분히 빠르게 추론 가능하기 때문).

Windows(VSCode) 실행 예시:
    python tools/export_onnx.py --weights ./best.pt --output ./inference/model/best.onnx
"""
import argparse
import shutil
import sys
from pathlib import Path
from typing import Optional


def find_best_pt(search_root: Path) -> Optional[Path]:
    """
    workspace 내에서 best.pt를 탐색한다.
    다른 팀원의 파일을 이동/삭제하지 않고 경로만 읽는다.
    """
    ignored_dirs = {"node_modules", ".git", ".venv", "venv"}
    for path in search_root.rglob("best.pt"):
        if ignored_dirs & set(path.parts):
            continue
        return path
    return None


def export(
    weights: Path,
    output: Path,
    imgsz: int,
    opset: int,
    simplify: bool,
    dynamic: bool,
) -> None:
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit(
            "ultralytics 패키지가 설치되어 있지 않습니다.\n"
            "이 변환 스크립트를 실행하는 PC(Windows 등)에서만 아래 명령으로 설치하세요:\n"
            "    pip install ultralytics"
        ) from exc

    model = YOLO(str(weights))
    exported_path = model.export(
        format="onnx",
        imgsz=imgsz,
        opset=opset,
        simplify=simplify,
        dynamic=dynamic,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(exported_path, output)
    print(f"[OK] ONNX 모델 저장 완료: {output}")
    print("다음 단계: python tools/inspect_model.py --weights " + str(output))


def main() -> None:
    parser = argparse.ArgumentParser(description="best.pt -> best.onnx 변환")
    parser.add_argument(
        "--weights",
        type=str,
        default=None,
        help="best.pt 경로 (생략하면 workspace 전체에서 자동 탐색)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./inference/model/best.onnx",
        help="변환 결과를 저장할 경로",
    )
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument(
        "--opset",
        type=int,
        default=12,
        help="Raspberry Pi의 onnxruntime과 호환성이 검증된 opset 버전",
    )
    parser.add_argument(
        "--simplify", type=lambda v: v.lower() != "false", default=True
    )
    parser.add_argument(
        "--dynamic", type=lambda v: v.lower() == "true", default=False
    )
    args = parser.parse_args()

    if args.weights:
        weights_path = Path(args.weights)
        if not weights_path.exists():
            print(f"[ERROR] 지정한 weights 파일을 찾을 수 없습니다: {weights_path}")
            sys.exit(1)
    else:
        # rpi_backend/tools/export_onnx.py 기준으로 workspace 루트를 계산한다.
        workspace_root = Path(__file__).resolve().parents[2]
        print(f"[INFO] --weights 미지정: {workspace_root} 아래에서 best.pt를 탐색합니다...")
        found = find_best_pt(workspace_root)
        if found is None:
            print(
                "[ERROR] best.pt를 찾을 수 없습니다.\n"
                "        rpi_backend/README.md STEP 1 안내에 따라 best.pt를 준비한 뒤 다시 실행하세요.\n"
                "        예) python tools/export_onnx.py --weights C:\\path\\to\\best.pt "
                "--output ./inference/model/best.onnx"
            )
            sys.exit(1)
        weights_path = found
        print(f"[INFO] best.pt 발견: {weights_path}")

    output_path = Path(args.output)
    export(weights_path, output_path, args.imgsz, args.opset, args.simplify, args.dynamic)


if __name__ == "__main__":
    main()
