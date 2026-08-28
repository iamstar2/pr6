# Raspberry Pi 5 (ARM64) 호환을 위해 공식 python slim 이미지를 사용한다.
FROM python:3.11-slim

WORKDIR /app

# OpenCV가 필요로 하는 최소 시스템 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
