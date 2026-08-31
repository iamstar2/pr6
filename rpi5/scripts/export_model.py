"""One-time conversion: download the PPE YOLOv8 checkpoint from Hugging Face and
export it to ONNX so the FastAPI server can run it with onnxruntime only
(no torch/ultralytics needed at serve time -> easy to port to Raspberry Pi 5 later).

Usage:
    python rpi5/scripts/export_model.py
"""
import json
import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download
from ultralytics import YOLO

REPO_ID = "Hansung-Cho/yolov8-ppe-detection"
FILENAME = "best.pt"
IMGSZ = 640

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {FILENAME} from {REPO_ID} ...")
    pt_path = hf_hub_download(repo_id=REPO_ID, filename=FILENAME)
    print(f"Downloaded to {pt_path}")

    model = YOLO(pt_path)
    print("Classes:", model.names)

    onnx_path = model.export(format="onnx", imgsz=IMGSZ, opset=12, simplify=True)
    onnx_path = Path(onnx_path)

    dest = MODELS_DIR / "ppe_yolov8n.onnx"
    shutil.copy(onnx_path, dest)
    print(f"Copied ONNX model to {dest}")

    classes_path = MODELS_DIR / "classes.json"
    classes_path.write_text(
        json.dumps({int(k): v for k, v in model.names.items()}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote class map to {classes_path}")
    print("Done. Point rpi5/config.yaml model.path at:", dest.as_posix())


if __name__ == "__main__":
    main()
