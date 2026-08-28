# rpi_backend — PPE 미착용 감지 Raspberry Pi Backend

ESP32-S3 카메라 → **이 폴더(receiver / inference / cloud)** → Supabase 로 이어지는
Raspberry Pi 5 백엔드 구현이다.

> 이 폴더는 팀 프로젝트 중 Raspberry Pi Backend 담당자의 작업 영역이다.
> ESP32 코드(.ino)와 Web(front-end) 코드는 이 폴더에 포함되어 있지 않으며, 건드리지 않는다.

## 전체 아키텍처

```
ESP32-S3 (팀원 담당)
   │ HTTP POST (JPEG)
   ▼
receiver  (:8000, 외부 노출)
   │ 내부 HTTP
   ▼
inference (:8001, 내부 전용) ── ONNX Runtime으로 YOLO 추론
   │ violation=true 일 때만
   ▼
cloud     (:8002, 내부 전용) ── Supabase Storage + DB
   │
   ▼
Supabase (Storage + violations 테이블)
   │
   ▼
Web 갤러리 (팀원 담당)
```

---

## STEP 1. best.pt 준비

이 팀원이 직접 학습한 가중치가 있다면 그 `best.pt`를 사용한다. 아직 없다면
아래 기본 탑재 모델을 Hugging Face에서 받아 우선 검증용으로 사용할 수 있다.

### 기본 탑재 모델: Hansung-Cho/yolov8-ppe-detection

- 출처: https://huggingface.co/Hansung-Cho/yolov8-ppe-detection
- 베이스: YOLOv8n (Ultralytics), 입력 640×640
- 성능(검증셋): mAP@0.50 = 0.744, mAP@0.50:0.95 = 0.436
- class(10종, `tools/inspect_model.py`로 실측 확인됨):
  `Hardhat, Mask, NO-Hardhat, NO-Mask, NO-Safety Vest, Person, Safety Cone, Safety Vest, machinery, vehicle`
  - 이 중 `NO-Hardhat`, `NO-Safety Vest`가 `.env.example`의 `NO_HELMET_CLASSES`/`NO_VEST_CLASSES` 기본값과 정확히 일치한다.
  - `Mask/NO-Mask`, `Safety Cone`, `machinery`, `vehicle`은 detection 결과에는 포함되지만
    현재 시스템은 안전모/안전조끼만 판정하므로 violation 판정에는 사용되지 않는다(무시됨).

**[Windows VSCode]**

```powershell
pip install huggingface_hub
python -c "from huggingface_hub import hf_hub_download; print(hf_hub_download(repo_id='Hansung-Cho/yolov8-ppe-detection', filename='best.pt', local_dir='.'))"
```

위 명령을 실행하면 `rpi_backend/best.pt`로 저장된다 (`.gitignore`에 의해 Git에는 커밋되지 않음).

`best.pt`가 아직 없다면 이후 STEP은 모델 없이도 계속 진행할 수 있다.
(receiver/cloud 서비스와 테스트는 모델 없이도 동작한다. inference 서비스만 실제 추론 시 오류를 반환한다.)

---

## STEP 2. best.pt → best.onnx 변환

**[Windows VSCode]**

```powershell
cd rpi_backend
python -m venv .venv
.venv\Scripts\activate
pip install ultralytics onnxruntime

python tools/export_onnx.py --weights ./best.pt --output ./inference/model/best.onnx
```

`--weights`를 생략하면 workspace 전체에서 `best.pt`를 자동으로 찾는다.

---

## STEP 3. ONNX 모델 클래스 확인 (매우 중요)

미착용 class 이름은 모델마다 다를 수 있으므로 반드시 실제 값을 확인한다.

**[Windows VSCode]**

```powershell
python tools/inspect_model.py --weights ./inference/model/best.onnx
```

기본 탑재 모델(Hansung-Cho/yolov8-ppe-detection) 기준 실제 출력:
```
사용 가능한 class 목록:
  0: Hardhat
  1: Mask
  2: NO-Hardhat
  3: NO-Mask
  4: NO-Safety Vest
  5: Person
  6: Safety Cone
  7: Safety Vest
  8: machinery
  9: vehicle
```

이 출력 결과를 보고 STEP 7의 `.env`에서 `NO_HELMET_CLASSES`, `NO_VEST_CLASSES` 값을 실제 이름과 맞게 수정한다.

> 모델에 `NO-Hardhat` 계열의 명시적인 미착용 class가 없고 `Person/Hardhat/Safety Vest` 같은
> 착용 class만 있다면, inference 서비스는 미착용을 함부로 확정하지 않고 로그로 경고만 남긴다.
> 이 경우 미착용 class를 추가 학습하거나 별도의 PPE-person 매칭 로직이 필요하다.

---

## STEP 4. Supabase 프로젝트 설정

1. https://supabase.com 에서 프로젝트 생성
2. 프로젝트 설정 → API 메뉴에서 아래 두 값을 확인
   - `Project URL` → `.env`의 `SUPABASE_URL`
   - `service_role` key → `.env`의 `SUPABASE_SERVICE_ROLE_KEY` (절대 외부 공개 금지)

---

## STEP 5. Supabase Storage bucket 생성

Supabase 대시보드 → Storage → New bucket

- 이름: `violations` (`.env`의 `SUPABASE_BUCKET`과 동일해야 함)
- Public/Private 여부는 Web 팀원과 협의하여 결정 (갤러리에서 이미지를 어떻게 노출할지에 따라 다름)

---

## STEP 6. database/create_violations.sql 실행

Supabase 대시보드 → SQL Editor → New query 에 `database/create_violations.sql` 내용을 붙여넣고 실행한다.

---

## STEP 7. .env 생성

**[Windows VSCode]**

```powershell
copy .env.example .env
```

`.env`를 열어 아래 값을 채운다.

- `NO_HELMET_CLASSES`, `NO_VEST_CLASSES` — STEP 3에서 확인한 실제 class 이름
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` — STEP 4에서 확인한 값

`.env`는 절대 Git에 커밋하지 않는다 (`.gitignore`에 등록되어 있음).

---

## STEP 8. Docker Compose 실행

**[Raspberry Pi Terminal]**

```bash
# 이 폴더(rpi_backend)를 Raspberry Pi로 옮긴 뒤 (git clone 또는 scp)
cd rpi_backend
docker compose up -d --build
```

---

## STEP 9. health check

**[Raspberry Pi Terminal]**

```bash
curl http://localhost:8000/health
```

정상이면:
```json
{"status": "healthy"}
```

---

## STEP 10. PC에서 테스트 이미지 HTTP POST

**[Windows VSCode]** (Raspberry Pi IP로 접속)

```powershell
curl.exe -X POST "http://<RASPBERRY_PI_IP>:8000/api/v1/frame" `
  -H "Content-Type: image/jpeg" `
  -H "X-Device-ID: test-device" `
  --data-binary "@samples/test.jpg"
```

응답 예시:
```json
{
  "status": "ok",
  "device_id": "test-device",
  "violation": true,
  "violation_types": ["NO_HARDHAT"],
  "detections": [...],
  "event_id": "...",
  "cloud_uploaded": true
}
```

---

## STEP 11. ESP32 연결

ESP32 담당 팀원에게 `INTEGRATION.md`를 전달한다.
ESP32 쪽 코드는 이 폴더에서 작성하지 않는다 — API 계약만 문서화되어 있다.

---

## 로컬 개발 / 테스트 (Docker 없이)

**[Windows VSCode]**

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install fastapi uvicorn httpx python-multipart opencv-python-headless numpy onnxruntime supabase pytest

pytest tests/ -v
```

Supabase key와 실제 YOLO 모델이 없어도 Mock 기반 테스트는 모두 통과해야 한다.

---

## 폴더 구조

```
rpi_backend/
├─ receiver/    # ESP32로부터 JPEG 수신, inference로 전달 (외부 노출: 8000)
├─ inference/   # ONNX Runtime 기반 YOLO 추론 + violation 판정 (내부 전용: 8001)
├─ cloud/       # violation 발생 시 Supabase Storage/DB 업로드 (내부 전용: 8002)
├─ tools/       # best.pt -> best.onnx 변환, 모델 class 확인 도구
├─ database/    # Supabase 테이블 생성 SQL
├─ tests/       # Mock 기반 단위 테스트
└─ samples/     # 로컬 테스트용 이미지 (git에는 커밋되지 않음)
```

## 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| inference 서비스가 500 에러 반환 | `best.onnx`가 `inference/model/`에 없음 → STEP 2 재실행 |
| 미착용인데 violation=false | STEP 3에서 확인한 class 이름과 `.env`의 `NO_HELMET_CLASSES`/`NO_VEST_CLASSES`가 불일치 |
| cloud_uploaded=false, reason=cooldown | 정상 동작 (같은 device+violation 조합이 `EVENT_COOLDOWN_SEC` 이내에 반복됨) |
| Supabase 업로드 실패 | `.env`의 `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` 확인, STEP 5/6 완료 여부 확인 |
