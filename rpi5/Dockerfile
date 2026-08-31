# Build from the repo root: docker compose -f rpi5/docker-compose.yml build
# (context is ".." so this can COPY the sibling cloud/ package into the image)
#
# Same Dockerfile is meant to run unmodified on a Raspberry Pi 5 later — every
# dependency in requirements.txt ships an aarch64 wheel, so `docker compose build`
# on the Pi itself just works. See rpi5/README.md.
FROM python:3.11-slim

WORKDIR /app

COPY rpi5/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY cloud/ ./cloud/
COPY rpi5/app/ ./app/
COPY rpi5/config.yaml ./config.yaml
COPY rpi5/models/ ./models/

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
