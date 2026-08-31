# 실무화 리팩토링 리포트

대상: ①ESP32-S3(PlatformIO/Edge Impulse) ②RPi5(FastAPI/ONNX YOLOv8) ③cloud/(Provider 추상화) ④web/(Next.js/Socket.IO)

작성일: 2026-08-31 · 코드 수정 전 분석 단계 (`production_hardening_prompt.md` 1단계)

---

## 0. 실행 전 정정한 전제 사항

원 지시서(`production_hardening_prompt.md`)를 실행하기 전 실제 코드와 대조한 결과, 다음 전제가 사실과 달라 먼저 바로잡았습니다.

1. **저장소 범위**: `.gitignore`상 `rpi5/`·`cloud/`는 원래 "다른 팀원이 별도 구현으로 교체할 로컬 참고 코드"로 GitHub에서 제외되어 있었고, git에는 이것과 무관한 구버전 `rpi_backend/`(receiver/inference/cloud 3-서비스 구조)가 실제로 커밋되어 있었습니다. → **팀 분리 전제를 버리고 이 저장소(`rpi5/`+`cloud/`)를 단일 소유로 새 GitHub 저장소(iamstar2/pr6)에 통합**하기로 확정. `rpi_backend/`는 `git rm`으로 삭제 스테이징, `.gitignore`에서 `/rpi5/`·`/cloud/` 제외 규칙 제거, 대신 실제 시크릿(`rpi5/.env`, Supabase service-role 키)과 실제 인물 사진 209장이 든 `rpi5/cloud/_mock_storage/`만 정밀 제외 처리 완료.
2. **request_id 발급 주체**: 원 지시서는 "ESP32에서 최초 생성한 request_id"를 전제로 추적 점검을 요청했으나, 실제로는 **RPi5가 `detect.py`에서 `uuid.uuid4()`로 최초 생성**하고 ESP32는 응답에서 받아 로그만 남깁니다(자체 생성 안 함). 아래 상관관계 추적 점검은 이 실제 흐름 기준으로 작성했습니다.

---

## 1. 예외 처리 및 로깅

### ESP32
| 항목 | 상태 | 근거 |
|---|---|---|
| 치명적 초기화 실패 시 재부팅 | ❌ 없음 (**높음**) | 카메라 초기화/버퍼 할당 실패 시 `esp32/src/main.cpp:314-329`에서 `esp_restart()` 없이 LED 점멸 무한루프로 정지 — 사람이 직접 전원을 재인가해야 복구 |
| 런타임 캡처 실패 처리 | ✅ 문제없음 | `fb_get()`/`fmt2rgb888`/`run_classifier` 실패는 로그 후 `return`, 다음 사이클 재시도 |
| 워치독(WDT) | ❌ 없음 (**높음**) | `esp_task_wdt` 관련 코드 0건 — HTTP 호출·추론이 블로킹돼도 자동 복구 수단 없음 |
| 로그 레벨링 | ❌ 없음 (**중간**) | `Serial.print*`만 30회+ 산재, `[ERR]`/`[Debug]` 등은 문자열 접두어일 뿐 컴파일타임 필터 아님. `platformio.ini`의 `CORE_DEBUG_LEVEL=1`은 ESP-IDF 내부 로그에만 영향, 앱 로그는 프로덕션에서도 그대로 출력됨 |
| 원격 로깅 | ❌ 없음 (**중간**) | USB Serial 전용, 현장 배포 후 재현 전엔 로그 확인 불가 |

### RPi5 (Python `logging`) — 1-1 세부 점검
| 점검 항목 | 상태 | 근거 |
|---|---|---|
| 로거/핸들러 레벨 명시적 분리 | ❌ 미흡 (**중간**) | `rpi5/app/main.py`에 `logging.basicConfig(level=INFO, ...)` 한 줄뿐. `getLogger("rpi5.events")`/`getLogger("rpi5.detect")`가 `setLevel()`을 별도 호출하지 않고 root 레벨에 암묵 위임 — "로거 레벨 vs 핸들러 레벨"이 각각 의도적으로 설정된 게 아니라 우연히 동작 |
| 로거 계층/propagate | ⚠️ 확인 필요 (**낮음**) | `propagate` 미설정(기본 True) — 현재는 핸들러가 root 하나뿐이라 중복 기록은 없지만, 향후 하위 모듈에 핸들러를 추가하면 중복 로깅 위험 |
| 로그 포맷 5요소 | ❌ 불완전 (**중간**) | `%(asctime)s %(levelname)s %(name)s: %(message)s`까지만 있고 **`filename:lineno` 누락** — 에러 위치 추적 어려움 |
| 로그 로테이션 | ❌ 없음 (**중간, RPi5는 SD카드라 더 치명적**) | `RotatingFileHandler` 없이 `basicConfig` 기본 `StreamHandler`(stdout)뿐. 컨테이너 로그 드라이버 로테이션 미설정 시 디스크 무한 증가 가능 |
| 시크릿 노출 | ✅ 문제없음 | `SUPABASE_KEY` 등이 로그 인자로 전달되는 지점 전수 확인 결과 없음 |

### 웹 (Node/Next.js)
| 항목 | 상태 | 근거 |
|---|---|---|
| 구조화 로깅(Winston/Pino) | ❌ 미도입 (**중간**) | `web/server.js` 전체가 `console.log`/`console.error` 7곳뿐 |
| try-catch 커버리지 | ⚠️ 부분적 (**낮음**) | 최상위 요청 핸들러(`server.js:73-122`)와 body 파싱은 커버되나, `io.on('connection')`(`server.js:132`) 콜백엔 예외 처리 없음 |
| 에러 응답 시 스택트레이스 노출 | ✅ 문제없음 | 500 응답은 `{ error: 'Internal server error' }`만 반환 |

### 분산 추적(Correlation ID) — 실제 흐름
`rpi5/app/routers/detect.py`에서 `request_id` 최초 생성 → 로그 기록 → `PPEResult`에 주입 → 웹으로 보내는 `live_payload`/`violation` payload에 포함 → 위반 시 `cloud/schemas.py`의 `ViolationRecord.id`로 매핑 → `cloud-status` 이벤트에도 동일 id 전파. **단일 UUID가 RPi5 로그·클라우드 레코드·웹 이벤트 3곳에 일관되게 이어짐 (문제없음)**. 단, ESP32 구간은 이 id의 "발급자"가 아니라 "수신 후 로깅만 하는 소비자"라는 점이 원 지시서 전제와 다름 (0번 항목 참고).

---

## 2. 보안 강화

| 컴포넌트 | 항목 | 상태 | 근거 |
|---|---|---|---|
| RPi5 | API 엔드포인트 인증 | ❌ 없음 (**높음**) | `/api/v1/detect` 등 라우터 전체에 API Key/토큰/`Depends(auth)` 0건. 임의 기기가 가짜 탐지 이미지 업로드 가능 |
| RPi5 | **경로 조작(Path Traversal)** | ❌ **취약 (높음, 신규 발견)** | `device_id`가 `Form(...)`으로 검증 없이 받아져 `key = f"{device_id}/{request_id}.jpg"`(`detect.py:128`)로 그대로 조합, `LocalMockStorageProvider`가 `self.images_dir / key`로 결합(`local_mock.py:39`) — `device_id="../../.."` 등으로 저장 경로 이탈 가능. 인증 부재와 결합 시 임의 파일 쓰기로 확대될 수 있어 **1순위 후보** |
| RPi5 | 입력 검증(파일 크기/타입) | ❌ 없음 (**높음**) | `content_type` 검사, 업로드 크기 제한 없이 `await image.read()`로 무제한 메모리 적재 — 인증 부재와 겹치면 DoS 벡터 |
| RPi5/cloud | 시크릿 분리 | ✅ 양호(로컬 정리로 개선) | `rpi5/.env`(실키) vs `.env.example`(플레이스홀더) 분리, 이번에 `.gitignore`에 `rpi5/.env`만 정밀 제외 추가 |
| 웹 | 엔드포인트 인증 | ❌ 없음 (**높음**) | `/api/events/*` 3개 전부 인증 없이 수신, 그대로 모든 브라우저에 브로드캐스트 |
| 웹 | CORS | ❌ 전체 허용 (**높음**) | `Access-Control-Allow-Origin: *` 하드코딩(`server.js:66,126-129`), Socket.IO cors도 `origin:'*'` |
| 웹 | 바디 크기 제한 | ✅ 구현됨 | `MAX_BODY_BYTES = 8*1024*1024`(`server.js:32`), 초과 시 413 |
| 웹 | 입력 검증 | ❌ 없음 (**중간**) | payload를 필드 검증 없이 그대로 `io.emit`으로 전달 |
| ESP32 | 자격증명 분리 | ✅ 문제없음 | `config.h.example`에 실제 값 없음(플레이스홀더만), `config.h`는 gitignore 처리 |
| ESP32 | 전송 구간 암호화/인증 | ❌ 평문 HTTP + 무인증 (**중간**) | `SERVER_BASE_URL="http://..."`(TLS 미사용), 요청에 공유 시크릿 헤더 없음 |

---

## 3. 코드 모듈화 및 아키텍처

- **ESP32**: HTTP 계층(`uploadDetection`/`uploadDetectionWithRetry`)은 잘 분리되어 있으나, bbox 임계값 필터링·쿨다운 판단·전송 인터벌 게이팅이 모두 `loop()`에 인라인되어 있음 (**낮음~중간**).
- **RPi5**: `cloud/base.py`의 `CloudStorageProvider` ABC가 `local_mock`/`supabase`를 완전히 상호교체 가능하게 설계되어 있어 Provider 추상화 자체는 **양호**. 다만 `routers/detect.py`가 추론 호출·중복판정·클라우드 업로드 오케스트레이션을 라우터 계층에 직접 포함 — 서비스 계층 분리 없음 (**낮음**, 현재 규모에선 치명적이지 않음).
- **웹**: `server.js`(147줄) 단일 파일에 라우팅·CORS·비즈니스 로직·Socket.IO 브로드캐스트가 혼재. `ROUTES` 테이블로 선언적 분리는 되어 있음 (**낮음~중간**).

---

## 4. 성능 및 최적화

| 컴포넌트 | 항목 | 상태 | 근거 |
|---|---|---|---|
| RPi5 | **추론의 이벤트루프 블로킹** | ❌ **문제 (높음)** | `detect()`는 `async def`이지만 내부 `detector.detect()`(onnxruntime `session.run` 포함)가 완전 동기 함수이고 `asyncio.to_thread` 등으로 오프로드하지 않음. `uvicorn`도 워커 1개(기본값) — 추론 중 다른 디바이스 요청·헬스체크·백그라운드 이벤트 emit이 모두 지연됨. RPi5 CPU 제약과 겹쳐 다중 카메라 운용 시 병목 심각 |
| RPi5 | 업로드/DB I/O 비동기화 | ✅ 문제없음 | `asyncio.to_thread`로 잘 오프로드됨(`local_mock.py`, `supabase_provider.py`) |
| RPi5 | N+1 쿼리 | ✅ 해당 없음 | 요청당 단건 처리 구조 |
| 웹 | 이미지 브로드캐스트 대역폭 | ⚠️ 주의 (**중간**) | base64 이미지를 압축/리사이즈 없이 연결된 모든 클라이언트에 verbatim relay — 클라이언트 수 증가 시 서버 아웃바운드 부하 커짐 |
| 웹 | 클라이언트 메모리 관리 | ✅ 문제없음 | `history` 배열이 `MAX_HISTORY=50`으로 매번 slice, 서버는 상태를 전혀 들고 있지 않음(즉시 emit 후 버림) |

---

## 5. 네트워크 안정성

| 구간 | 항목 | 상태 | 근거 |
|---|---|---|---|
| ESP32→RPi5 | 재시도/백오프/타임아웃 | ✅ 구현됨 | `HTTP_MAX_RETRIES=3`, 지수 백오프(`backoff *= 2`), `HTTP_TIMEOUT_MS=8000` 실제 적용 |
| ESP32→RPi5 | 3회 실패 시 처리 | ❌ 유실 (**중간**) | 재시도 소진 시 프레임 그냥 폐기, 로컬 큐잉 없음 — 네트워크 순단 시 위반 증거 소실 |
| ESP32 WiFi | 재연결 | ⚠️ 비일관 (**낮음~중간**) | 최초 연결(`wifiConnect`)은 견고하나 런타임 끊김 처리는 `WiFi.reconnect()` 단순 반복 — 라우터 재부팅급 장애엔 복구 안 될 가능성 |
| RPi5→웹 | 재시도/큐잉 | ❌ 없음, best-effort (**중간**) | `events.py`의 `_post()`는 단발 시도 후 실패 시 경고 로그만 남기고 폐기 — 웹이 잠깐 다운되면 이벤트 영구 유실 |
| RPi5→클라우드 | 업로드 실패 시 재처리 | ❌ 없음 (**중간, 컴플라이언스 영향**) | 실패 시 `status="failed"`로 웹에만 알리고 로컬 재처리 큐/파일 없음 — 위반기록 손실 가능 |
| 웹 프론트 | WebSocket 재연결 | ✅ 견고함 | `reconnection:true`, `reconnectionDelay:1000` 명시 설정 + 연결 상태 UI 배지. 단, 끊긴 동안의 이벤트 재전송/버퍼링은 구조적으로 없음(설계상 감수 가능한 낮은 리스크) |

---

## 6. 개인정보 및 데이터 처리 정책

- **이미지 보존 기간**: `rpi5/cloud/_mock_storage/`에 실제 인물이 찍힌 위반 이미지 209장이 **무기한 보관**되고 있고, 코드상 retention 정책이 전혀 없음 (**중간, 이번에 최소한 git 커밋 대상에선 제외 처리 완료**). Supabase 경로 사용 시에도 버킷 라이프사이클 정책 코드/문서 없음.
- **웹 클라이언트**: base64 이미지를 최대 50건 브라우저 메모리(React state)에 보관, 만료 정책 없음(새로고침 시에만 소멸) — 세션 동안 민감 이미지 상주 (**중간**).
- **접근 권한**: RPi5 엔드포인트 인증 부재(2번 항목)와 결합하면 사실상 누구나 위반 이미지를 트리거·열람할 수 있는 경로가 있어 개인정보 노출 리스크로 이어짐.
- **얼굴 마스킹**: 현재 어떤 컴포넌트에도 블러/마스킹 처리 없음 — PPE 위반 여부 판별에는 얼굴 식별이 불필요하므로, 저장 전 얼굴 영역 블러 처리를 검토 권장(선택 사항으로 유지).

---

## 7. 배포 환경 (멀티 아키텍처)

- `rpi5/Dockerfile`은 `python:3.11-slim` 베이스(멀티아키 매니페스트 지원)에 `requirements.txt` 전 패키지가 aarch64 wheel 제공 — 구성 자체는 **문제없음**.
- 다만 `Dockerfile`/`docker-compose.yml` 어디에도 `platform: linux/arm64` 명시가 없어, PC(x86)에서 `docker buildx` 없이 빌드하면 자동으로 ARM64 이미지가 만들어지지 않음. 현재는 "RPi5 본체에서 직접 빌드"를 전제로 회피하고 있는 상태로, 교차 빌드(CI에서 이미지 미리 빌드 등) 시나리오 대비는 안 되어 있음 (**낮음**).

---

## 8. 테스트 및 배포 준비

- **테스트 부재**: `rpi5/`, `cloud/`, `web/` 어디에도 pytest/Jest 테스트 파일이 없음(재확인 완료). RPi5의 유일한 검증 수단은 수동 e2e 스크립트(`scripts/e2e_mock_test.py`), 웹은 `scripts/simulate-events.sh`(수동 curl). (삭제한 구버전 `rpi_backend/tests/`에는 pytest 3개가 있었으나 현재 구조와 무관해져 참고 가치 낮음.)
- **RPi5 pytest 도입 시 모킹 필요 지점**: ① `supabase_provider.py`의 `create_client`/`storage`/`table` 호출, ② `events.py`의 `httpx.AsyncClient.post`(웹 호출), ③ `onnxruntime.InferenceSession`, ④ `LocalMockStorageProvider`의 파일시스템 I/O(`tmp_path` 픽스처로 대체 가능).
- **ESP32 테스트 가능 영역**: 쿨다운 판단·인터벌 게이팅·bbox 필터링이 현재 `loop()` 내부 지역 변수/인라인 로직에 묶여 있어 순수 함수로 추출되지 않으면 PlatformIO native 테스트가 불가능. `isCooldownActive(now, last, cooldownMs)`, `evaluateDetections(result, threshold)` 형태로 분리 시 하드웨어 없이 검증 가능해짐.
- **CI 파이프라인**: `.github/workflows/`가 저장소 어디에도 없음 — 신규 도입 필요.

---

## 우선순위 제안 (심각도 기준)

**높음 — 외부에서 실제 악용 가능한 항목**
1. RPi5 `device_id` 경로 조작(Path Traversal) 취약점 — 인증 부재와 결합 시 임의 파일 쓰기로 확대 가능
2. RPi5 FastAPI 엔드포인트 인증 부재 + 입력 검증(파일 크기/타입) 부재
3. 웹 대시보드 `/api/events/*` 인증 부재 + CORS 전체 허용
4. ESP32 카메라 초기화 실패 시 무한정지(재부팅 없음), 워치독 부재
5. RPi5 추론의 이벤트루프 블로킹 (성능 병목, 다중 디바이스 운용 시 치명적)

**중간 — 데이터 유실/컴플라이언스/운영 가시성**
6. RPi5→웹, RPi5→클라우드 실패 시 재시도/재처리 큐 부재 (이벤트·위반기록 유실)
7. 로깅 체계 정비 (ESP32 로그레벨, RPi5 포맷/로테이션, 웹 구조화 로깅)
8. 이미지 보존기간 정책 부재 (개인정보)
9. 테스트/CI 전무

**낮음 — 구조적 개선**
10. 모듈화(server.js, ESP32 loop(), RPi5 라우터 비대화), Docker 멀티아키 명시

---

원 지시서(`production_hardening_prompt.md`) 2단계 방침대로, 위 우선순위 중 **1순위로 어느 것부터 진행할지 확인받은 뒤** 한 번에 하나씩 수정 → 동작 확인 → 결과 공유 순서로 진행하겠습니다.
