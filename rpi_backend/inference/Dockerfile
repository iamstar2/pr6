# Raspberry Pi 5 (ARM64)에서 실행되므로 torch 없이 onnxruntime만 사용한다.
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# best.onnx는 tools/export_onnx.py 실행 결과물로 채워진다 (레포에는 커밋하지 않음).
COPY model ./model

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
