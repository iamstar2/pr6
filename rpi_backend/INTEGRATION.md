# Integration Guide

이 문서는 ESP32 담당 팀원과 Web 담당 팀원이 Raspberry Pi Backend와 연동할 때 참고하는 API 계약 문서다.
ESP32 코드나 Web 코드는 이 저장소(rpi_backend)에 포함되어 있지 않다.

---

## 1. ESP32 → Raspberry Pi

### Endpoint

```
POST http://<PI_IP>:8000/api/v1/frame
```

`<PI_IP>`는 Raspberry Pi 5의 실제 IP 주소로 대체한다 (예: `192.168.0.42`).

### 권장 방식: raw JPEG binary

```
POST /api/v1/frame HTTP/1.1
Host: <PI_IP>:8000
Content-Type: image/jpeg
X-Device-ID: esp32-s3-01
X-Captured-At: 2026-08-28T10:15:30+09:00
Content-Length: <바이트 수>

<JPEG raw bytes>
```

- `Content-Type: image/jpeg` 필수
- `X-Device-ID` (선택): 카메라 식별자. 생략 시 `unknown-device`로 기록됨
- `X-Captured-At` (선택): ISO8601 형식의 촬영 시각. 생략 시 `null`로 기록됨
- Body: JPEG 파일의 raw bytes 그대로

### 대안 방식: multipart/form-data

ESP32 HTTPClient 라이브러리 구현에 따라 raw body 전송이 어려운 경우 아래 방식도 지원한다.

```
POST /api/v1/frame HTTP/1.1
Host: <PI_IP>:8000
Content-Type: multipart/form-data; boundary=----XXXX
X-Device-ID: esp32-s3-01

------XXXX
Content-Disposition: form-data; name="file"; filename="frame.jpg"
Content-Type: image/jpeg

<JPEG raw bytes>
------XXXX--
```

파일 필드 이름은 `file`을 권장한다 (다른 이름이어도 receiver가 첫 번째 파일 필드를 찾아 처리한다).

### 응답 예시

```json
{
  "status": "ok",
  "device_id": "esp32-s3-01",
  "ppe_status": "VIOLATION",
  "violation": true,
  "violation_types": ["NO_HARDHAT"],
  "detections": [
    {
      "class_name": "NO-Hardhat",
      "violation_type": "NO_HARDHAT",
      "confidence": 0.87,
      "bbox": { "x1": 120, "y1": 84, "x2": 312, "y2": 410 }
    }
  ],
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "cloud_uploaded": true
}
```

- `ppe_status`: 판정 3단계 중 하나
  - `"COMPLIANT"` (착용) — 사람이 감지됐고 안전모/안전조끼를 모두 착용
  - `"VIOLATION"` (미착용) — 사람이 감지됐고 안전모/안전조끼 중 하나 이상 미착용 → **이 경우만 Supabase로 전달됨**
  - `"NO_PERSON"` (이상없음) — 사람 자체가 감지되지 않음 (미착용 물체만 있어도 판정하지 않음)
- `violation`: `ppe_status == "VIOLATION"`일 때만 `true` (즉 사람이 없으면 아무리 미착용 class가 잡혀도 `false`)
- `cloud_uploaded`: Supabase에 실제로 업로드되었는지 여부. `false`인 경우 `reason`(`"no_violation"` 또는 `"cooldown"`) 또는 `cloud_error` 필드를 함께 확인한다.

### Health check

```
GET http://<PI_IP>:8000/health
```

```json
{ "status": "healthy" }
```

### 참고: 에러 응답

| 상황 | HTTP status | body |
|---|---|---|
| 빈 이미지 | 400 | `{"status":"error","message":"빈 이미지입니다."}` |
| JPEG decode 실패 | 400 | `{"status":"error","message":"JPEG로 decode할 수 없는 이미지입니다."}` |
| inference 서비스 연결 실패 | 502 | `{"status":"error","message":"inference 서비스에 연결할 수 없습니다."}` |

---

## 2. Web 팀원에게: Supabase `violations` 테이블 구조

Web에서는 `violations` 테이블을 `created_at DESC` 순서로 조회하면 최신 위반 이벤트 갤러리를 만들 수 있다.

```sql
select created_at, device_id, violation_types, max_confidence, detections, image_path
from violations
order by created_at desc;
```

### 컬럼 설명

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | uuid | 기본 키 |
| `created_at` | timestamptz | 서버가 이벤트를 기록한 시각 (정렬 기준) |
| `captured_at` | timestamptz, nullable | ESP32가 촬영한 시각 (없을 수 있음) |
| `device_id` | text | 카메라 식별자 |
| `violation_types` | text[] | 예: `{NO_HARDHAT}`, `{NO_HARDHAT, NO_SAFETY_VEST}` |
| `max_confidence` | float | 미착용 detection 중 최고 confidence |
| `detections` | jsonb | 전체 detection 배열 (class_name, violation_type, confidence, bbox) |
| `image_path` | text | Storage 상의 경로. 예: `2026/08/28/550e8400-....jpg` |
| `model_name` | text | 판정에 사용된 모델 이름 |
| `model_version` | text, nullable | 모델 버전 |

### 이미지 URL 만들기

`image_path`는 Storage 내부 경로만 저장되어 있다. 실제 이미지 URL은 Supabase Storage API로 만든다.

- Public bucket인 경우: `SUPABASE_URL/storage/v1/object/public/violations/<image_path>`
- Private bucket인 경우: Supabase client의 `createSignedUrl()` 사용 (Web 팀원 판단에 맡김)

버킷을 public/private 중 무엇으로 할지는 Web 팀원과 상의해서 결정한다 (README STEP 5 참고).
