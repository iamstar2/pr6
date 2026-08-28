# 연동 가이드 — ②RPi5/③클라우드를 새로 구현하는 팀원용

이 저장소(GitHub)에는 **①ESP32-S3**와 **④웹 대시보드**만 올라갑니다. ②RPi5 판별 서버와
③클라우드 저장은 팀원이 별도로 구현합니다 (로컬에 있던 참고 구현은 `.gitignore`로 제외됨,
아래 계약만 지키면 그 구현을 몰라도 됩니다).

새로 구현할 RPi5 서버가 **① ESP32로부터 받는 입력**과 **④웹으로 보내야 하는 출력**, 이 두
계약만 지키면 ESP32/웹 코드는 한 줄도 안 건드리고 바로 통합됩니다.

---

## 1. ESP32 → RPi5 (당신의 서버가 구현해야 할 엔드포인트)

```
POST {SERVER_BASE_URL}/api/v1/detect     (ESP32의 esp32/include/config.h에서 경로 확인)
Content-Type: multipart/form-data
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `image` | file (JPEG) | 파일명 `capture.jpg`, `Content-Type: image/jpeg`. 고정 해상도 640x480(VGA) — `esp32/include/config.h`의 `CAPTURE_COLS`/`CAPTURE_ROWS`로 확인 가능 |
| `device_id` | string | 카메라 노드 식별자 (예: `esp32-01`) |
| `timestamp` | string | ISO8601 UTC (예: `2026-08-28T10:00:00Z`). NTP 동기화 전이면 placeholder일 수 있음 |
| `confidence` | string(float) | ESP32 FOMO 모델의 "사람 감지" confidence (0~1) — RPi5의 PPE 판별 confidence와는 다른 값 |

**응답 (필수)**:
```json
{ "received": true, "request_id": "임의의 고유 문자열(uuid 권장)" }
```
- HTTP 2xx로 응답해야 함. 2xx가 아니면 ESP32가 재시도합니다.
- ESP32는 응답 바디에서 `request_id`를 파싱해 로그만 남기고, 없어도 실패 처리하진 않습니다 —
  그래도 `violation_detected`/`cloud_upload_status`를 request_id로 매칭하는 웹 쪽을 위해
  **매 요청마다 새 uuid를 만들어 계속 이 값으로 응답**해주세요.

**타이밍/재시도 (참고만 하면 됨, 서버 구현과 무관)**:
- ESP32는 응답을 최대 8초(`HTTP_TIMEOUT_MS`) 기다립니다 — 그 안에 응답 주세요 (무거운 추론은
  비동기로 돌리고 먼저 ack부터 보내는 걸 권장).
- 실패 시 최대 3회(`HTTP_MAX_RETRIES`) 재시도, 0.5s/1s/2s 백오프.
- 사람이 계속 프레임에 있어도 최소 5초(`CAPTURE_COOLDOWN_MS`) 간격으로만 전송합니다 — 너무
  잦은 요청 걱정 안 해도 됩니다.

---

## 2. RPi5(당신의 서버) → 웹 대시보드 (당신이 호출해야 할 엔드포인트)

웹 대시보드는 `PORT`(기본 `4000`)에서 아래 3개 HTTP 엔드포인트를 받고, 그대로 Socket.IO로
브라우저에 재전송합니다. **필드명을 정확히 맞춰야** 화면에 제대로 표시됩니다.

### 2-1. `POST /api/events/live-frame` — 매 판별마다 (위반 여부 무관)

```json
{
  "request_id": "uuid",
  "device_id": "esp32-01",
  "timestamp": "2026-08-28T10:00:00Z",
  "helmet_detected": false,
  "vest_detected": true,
  "violation": true,
  "confidence": 0.87,
  "bbox": [120.5, 60.0, 160.0, 240.0],
  "image_base64": "<원본 JPEG를 base64로 인코딩한 문자열>",
  "image_width": 640,
  "image_height": 480,
  "image_ref": "아무 문자열이나 가능 (화면에 안 씀)"
}
```

- **⚠️ 중요 — 프레임에 사람이 없으면 반드시 `violation: false`, `helmet_detected: true`,
  `vest_detected: true`로 보내세요.** ESP32의 FOMO는 오탐지가 있을 수 있어서, 당신의 RPi5가
  실제로 사람을 못 찾았는데도 "헬멧/조끼 미검출"을 곧이곧대로 위반 처리하면 안 됩니다
  (이전에 이 가드가 없어서 빈 프레임이 전부 위반으로 오판되는 버그가 있었습니다 — 사람이
  실제로 검출됐을 때만 헬멧/조끼 판정을 하고, 아니면 무조건 `violation: false`로 두세요).
- **`bbox`는 `image_width`/`image_height` 기준 픽셀 좌표**여야 합니다 (다른 기준이면 웹에서
  박스 위치가 틀어짐).
- **`image_base64`**: ESP32가 보낸 그 이미지를 그대로 base64 인코딩해서 넣으면 됩니다
  (ESP32가 이미 보내고 있는 이미지라 추가 비용 없음). 웹의 "실시간 감지 화면"이 이 이미지 위에
  bbox를 그립니다.

### 2-2. `POST /api/events/violation` — `violation: true`인 경우에만, 위와 동일한 payload

토스트 알림 + 위반 이력 리스트에 새 항목이 추가됩니다. **2-1과 완전히 같은 payload**를
그대로 보내면 됩니다 (violation일 때 live-frame과 violation 둘 다 호출).

### 2-3. `POST /api/events/cloud-status` — 클라우드 업로드 완료/실패 시

```json
{
  "request_id": "uuid (2-2에서 보낸 request_id와 반드시 일치)",
  "device_id": "esp32-01",
  "status": "success",
  "image_url": "https://.../violation.jpg",
  "timestamp": "2026-08-28T10:00:00Z"
}
```
- `status`는 `"success"` 또는 `"failed"`. 실패 시 `image_url`은 빈 문자열 `""`.
- `request_id`가 2-2의 위반 이벤트와 일치해야 웹에서 같은 이력 항목에 "저장 완료/실패" 뱃지가
  붙습니다.

### 공통 사항
- 세 엔드포인트 다 `Content-Type: application/json`, 아무 오리진이나 허용(CORS 이미 설정됨).
- 요청 바디 최대 8MB까지 받습니다 (base64 이미지 포함이라 넉넉하게 잡혀있음).
- 웹 서버 주소는 개발 환경에선 보통 `http://localhost:4000` — RPi5가 웹과 다른 PC에서 돌면
  "localhost"가 그 PC 자신을 가리키게 되니, 웹이 떠 있는 PC의 실제 LAN IP로 바꿔야 합니다.

---

## 참고

- 이 계약대로 실제로 동작하는 참고 구현이 이 컴퓨터의 `rpi5/`, `cloud/` 폴더에 있습니다
  (GitHub엔 안 올라가지만 로컬엔 남아있음) — 막히는 부분 있으면 그 코드를 참고하셔도 됩니다.
- ESP32가 실제로 보내는 필드/타이밍의 근거 코드: `esp32/src/main.cpp`의
  `uploadDetection()`/`uploadDetectionWithRetry()`.
- 웹이 기대하는 payload의 근거 코드: `web/server.js`(수신), `web/app/page.js` +
  `web/components/LiveDetectionView.js` / `ViolationHistory.js`(사용하는 필드).
