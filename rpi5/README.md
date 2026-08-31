# rpi5/ — PPE 판별 서버 (현재 PC에서 개발/구동, 추후 Raspberry Pi 5로 이식)

> **2026-08-31 갱신**: 팀 분리 전제를 접고 이 폴더를 저장소에 포함시키기로 결정했습니다 —
> 더 이상 "팀원이 별도 구현" 대상이 아니라 이 프로젝트의 실제 RPi5 구현체입니다. 실제 시크릿
> (`.env`)과 런타임 산출물(`cloud/_mock_storage/`, `data/`, `logs/`)만 `.gitignore`로 제외됩니다.
> ESP32/웹과 맞춰야 하는 계약 자체는 여전히 유효하므로 [`INTEGRATION.md`](../INTEGRATION.md)도
> 참고하세요.

> **현재 상태**: 원래 작업 지시서(`claude_code_prompt.md` 4.2)는 이 모듈을 "스켈레톤 + mock 추론"으로만
> 요구했지만, 실제 라즈베리파이 5 보드가 아직 없어서 **PC에서 실제 YOLOv8 PPE 모델로 동작하는 상태**로
> 구현했습니다. mock 모드도 그대로 남아있어 모델 파일 없이도 테스트할 수 있습니다.

## 무엇이 실제로 동작하나

- FastAPI 서버가 `POST /api/v1/detect`로 ESP32의 이미지를 받는다.
- [Hansung-Cho/yolov8-ppe-detection](https://huggingface.co/Hansung-Cho/yolov8-ppe-detection) (YOLOv8n,
  10-class PPE 검출 모델)을 ONNX로 변환해 **onnxruntime**으로 직접 추론한다 (torch/ultralytics는
  변환 스크립트에서만 쓰고, 서빙 이미지에는 포함하지 않음 — 이식성을 위해 의도적으로 뺐다).
- 위반 발생 시 `cloud/`(현재 `LocalMockStorageProvider`)에 이미지·기록을 저장.
- 모든 판별 결과와 위반/업로드 상태를 웹 백엔드로 이벤트 전송 (`app/events.py`).

## 클래스 매핑 (모델 실제 출력, `config.yaml`에도 기록됨)

| id | class | 의미 |
|----|-------|------|
| 0 | Hardhat | 안전모 착용 |
| 1 | Mask | 마스크 착용 |
| 2 | NO-Hardhat | 안전모 미착용 |
| 3 | NO-Mask | 마스크 미착용 |
| 4 | NO-Safety Vest | 안전조끼 미착용 |
| 5 | Person | 사람 |
| 6 | Safety Cone | 안전 콘 |
| 7 | Safety Vest | 안전조끼 착용 |
| 8 | machinery | 중장비 |
| 9 | vehicle | 차량 |

`infer_ppe()`는 이 중 Hardhat/NO-Hardhat/Safety Vest/NO-Safety Vest/Person만 사용합니다
(Mask, Safety Cone, machinery, vehicle은 이번 파이프라인에서 미사용 — 필요해지면 `app/inference.py`에서
확장). 프레임에 사람이 여러 명이면 confidence가 가장 높은 사람 bbox 하나만 대표로 사용하는 v1
휴리스틱이며, 사람별 개별 판정(사람↔장비 IoU 매칭)은 TODO로 남아있습니다.

## 로컬(PC) 실행

```bash
# 0) (최초 1회) 개인 설정값 파일 생성 — 기본값 그대로도 local_mock으로 바로 동작함
cp .env.example .env

# 1) (최초 1회) 모델 다운로드 + ONNX 변환 — torch/ultralytics 필요
pip install ultralytics huggingface_hub
python scripts/export_model.py
# -> rpi5/models/ppe_yolov8n.onnx, rpi5/models/classes.json 생성됨

# 2) 서빙 의존성 설치 (torch 불필요)
pip install -r requirements.txt

# 3) 서버 실행 (repo root에서 실행해야 ../cloud 패키지를 찾을 수 있음)
cd rpi5
PYTHONPATH=.. uvicorn app.main:app --reload --port 8000
```

## Docker로 실행 (PC / RPi5 공통)

```bash
cp rpi5/.env.example rpi5/.env   # 최초 1회 — docker-compose.yml이 이 파일을 env_file로 읽음
# repo root에서
docker compose -f rpi5/docker-compose.yml up --build
```

`rpi5/Dockerfile`은 `requirements.txt`만 설치합니다 (torch 없음) — 모델은 미리 변환해서
`rpi5/models/`에 넣어두거나(권장), 컨테이너 안에서 별도로 변환 스크립트를 돌려도 됩니다.

## 동작 확인 (curl)

```bash
curl -X POST http://localhost:8000/api/v1/detect \
  -F "image=@/path/to/some.jpg;type=image/jpeg" \
  -F "device_id=esp32-01" \
  -F "timestamp=2026-08-28T10:00:00Z" \
  -F "confidence=0.91"
# -> {"received": true, "request_id": "..."}
# DEVICE_API_KEY가 설정되어 있으면 위 요청에 -H "X-API-Key: <값>" 을 추가해야 401을 피할 수 있음.
curl http://localhost:8000/health
```

---

## 테스트

```bash
pip install -r requirements-dev.txt   # pytest, pytest-asyncio, ruff

pytest                    # 전체 (tests/unit + tests/integration)
pytest tests/unit         # 단위 테스트만
pytest tests/integration  # 통합 테스트만 (FastAPI TestClient, local_mock provider —
                           # 외부 네트워크 호출 없음. conftest.py가 CLOUD_PROVIDER를
                           # 강제로 local_mock으로 고정하므로 실수로 실제 Supabase에
                           # 요청을 보낼 일은 없음)

ruff check .               # lint (CI와 동일한 검사)
```

CI에서도 자주 쓰지만 로컬 반복 수정 중에 특히 유용한 옵션:
- `pytest -x` — 첫 실패에서 즉시 중단. 원인 하나에 집중할 때.
- `pytest --lf` — 직전 실행에서 실패한 테스트만 재실행. 수정→재확인 루프를 빠르게 돌릴 때.
- `pytest -k <표현식>` — 이름으로 필터링 (예: `pytest -k retry_queue`).

## Raspberry Pi 5로 이식하는 방법 (나중에 보드가 생기면)

이식 목표는 **코드/Dockerfile을 바꾸지 않고** RPi5에서 그대로 빌드/실행하는 것입니다.

1. **코드를 RPi5로 옮긴다** (git clone 또는 `rpi5/` + `cloud/` 폴더를 scp).
2. **모델은 미리 변환해서 옮긴다.** `scripts/export_model.py`는 torch가 필요해서 RPi5에서 직접
   돌리면 느리고 무겁습니다 — PC에서 변환한 `rpi5/models/ppe_yolov8n.onnx`와 `classes.json`만
   복사하는 것을 권장합니다.
3. **RPi5에서 그대로 빌드**:
   ```bash
   docker compose -f rpi5/docker-compose.yml up --build
   ```
   `requirements.txt`의 모든 패키지(`onnxruntime`, `opencv-python-headless`, `numpy`, `fastapi` 등)는
   공식 aarch64(manylinux_aarch64) wheel을 제공하므로 Pi에서 `pip install`이 x86과 동일하게 동작합니다.
4. **`WEB_BACKEND_URL`을 확인한다.** Docker Desktop 전용 DNS인 `host.docker.internal`은 리눅스(RPi OS)
   Docker Engine에서 기본 지원되지 않을 수 있습니다 — `docker-compose.yml`의
   `extra_hosts: host.docker.internal:host-gateway`가 이를 보완하지만, 안 되면 웹 백엔드의 실제
   IP(`http://<web-host>:4000`)로 바꾸세요.
5. **ESP32의 `SERVER_BASE_URL`을 RPi5의 실제 IP로 바꾼다** (`esp32/include/config.h`).
6. **성능 확인.** RPi5(Cortex-A76 쿼드코어)에서 YOLOv8n @640px onnxruntime CPU 추론은 대략
   200~400ms/frame 수준이 기대됩니다(실측 필요). ESP32 쪽 `HTTP_TIMEOUT_MS`가 이보다 넉넉한지
   확인하세요. 더 빠르게 하려면:
   - `config.yaml`의 `model.input_size`를 낮추고 모델을 그 크기로 재변환 (예: 480, 416)
   - `onnxruntime`을 XNNPACK/ARM 최적화 빌드로 교체
   - 프레임 스킵(연속 위반 프레임은 쿨다운으로 이미 ESP32 쪽에서 걸러짐 — `CAPTURE_COOLDOWN_MS` 참고)

## 클라우드 저장 설정 (Supabase)

`rpi5/.env`(gitignore, `cp .env.example .env`로 생성) 하나에 이 서버가 필요한 모든 개인 설정값이
모여 있습니다 — Wi-Fi처럼 사람마다 달라지는 값이라 코드/`config.yaml`이 아니라 여기 둡니다.
`CLOUD_PROVIDER=local_mock`(기본, 계정 불필요) 또는 `CLOUD_PROVIDER=supabase` +
`SUPABASE_URL`/`SUPABASE_KEY`/`SUPABASE_BUCKET`/`SUPABASE_TABLE`. Supabase 프로젝트 준비 절차는
[`cloud/README.md`](../cloud/README.md) 참고 — 이번 세션은 실 Supabase 계정이 없어 코드만
작성했고 라이브 업로드는 검증하지 못했습니다.

## 구현 필요 항목 (체크리스트)

- [ ] Supabase 실계정으로 라이브 테스트 (버킷 public 설정, `supabase_schema.sql` 실행 여부 확인)
- [ ] (선택) Supabase 외 다른 provider가 필요해지면 `cloud/providers/remote_stub.py` 참고 (`cloud/README.md`)
- [ ] 다중 인물 프레임에서 사람별 PPE 개별 판정 (현재는 confidence 최고 1명만 대표)
- [ ] 실제 RPi5 보드에서 추론 속도 실측 및 `CAPTURE_INTERVAL_MS`/`HTTP_TIMEOUT_MS` 튜닝
- [ ] (선택) 부정확한 mask/안전콘 클래스도 활용해 위반 유형 세분화
- [ ] 운영 배포 전 `DEVICE_API_KEY`/`WEB_INGRESS_TOKEN`/`web/ALLOWED_ORIGIN` 실제 값으로 설정
      (현재 기본값은 전부 "인증 없음/전체 허용" — 로컬 개발 전용)
- [ ] `retry_queue`(`rpi5/data/`)에 디스크 사용량 상한이 없음 — 클라우드 장애가 길어지면
      무한정 쌓임. 최대 보관 개수/기간 정책 추가 검토
- [ ] `LOG_SHIP_URL`은 훅만 있고 실제 로그 수집 서버(Loki/ELK/CloudWatch 등) 연동은 미검증
- [ ] `web/`의 `next@14.2.35`에 `npm audit`으로 발견된 High severity CVE 다수 — 16.x 메이저
      업그레이드 필요 (breaking change 있어 별도 작업으로 분리)
