# 리팩토링 결과 리포트 — 4대 고려사항 + CI/CD(Pytest) 파이프라인

대상 커밋 범위: 2026-08-31 작업분 (`HARDENING_REPORT.md` 1순위 항목 + `production_hardening_addendum.md` 9~13번을 함께 반영). 아래 각 항목은 실제로 수정한 파일/함수를 기준으로 작성했습니다.

---

## 1. 파라미터화 및 가독성

### Before

- `rpi5/app/config.py`의 환경변수 기반 필드(`host`, `port`, `web_backend_url` 등)가 **Pydantic 클래스 정의 시점(모듈 import 시점)에 `os.getenv(...)`로 한 번만 평가**되는 구조였습니다. `rpi5/.env`를 읽는 `load_dotenv()`는 `cloud/factory.py`에만 있었고, 그마저도 `app.config`보다 나중에 import되어(`app/main.py`가 `app.config`를 먼저 import) 로컬 개발(`uvicorn` 직접 실행) 환경에서 `.env`의 값이 실제로 반영되지 않을 수 있는 잠재 버그가 있었습니다.
- RPi5 `/api/v1/detect`에 인증이 전혀 없었고, `device_id`는 검증 없이 그대로 파일 경로(`cloud/providers/local_mock.py`의 `images_dir / key`)에 쓰였습니다 — `device_id="../../etc"` 같은 값으로 경로 조작(path traversal)이 가능했습니다.
- 업로드 크기 제한, `Content-Type` 검증이 없었습니다.
- 웹 대시보드(`web/server.js`)는 CORS를 `Access-Control-Allow-Origin: *`로 하드코딩하고, `/api/events/*`에 인증이 없었습니다.
- 클라우드 Provider 추상화(`cloud/base.py`)는 이미 잘 되어 있었으나(ABC 2개 메서드), 나머지 모듈(RPi5 인증, 웹 인증, 로깅)은 하드코딩된 상수/기본값에 의존했습니다.
- dev/staging/production 프로파일 개념이 전혀 없었습니다.

### After

- **`rpi5/app/config.py` 재설계**: 환경변수를 읽는 로직을 `_env_overrides()` 함수로 분리해 `get_config()` 호출 시점(캐시 클리어 후)마다 다시 읽도록 변경. `load_dotenv()`도 `config.py` 최상단으로 옮겨 어떤 진입점(uvicorn 직접 실행/Docker/pytest)에서도 `.env`가 먼저 로드되도록 수정. 이 리팩토링 덕분에 테스트(`rpi5/tests/unit/test_config.py`)에서 `monkeypatch.setenv(...)` → `get_config.cache_clear()`가 실제로 검증 가능한 구조가 됐습니다.
- **신규 파라미터화된 값** (전부 `rpi5/.env` / `rpi5/.env.example`, `web/.env.example`로 분리, 시크릿 아님):
  `DEVICE_API_KEY`, `MAX_UPLOAD_BYTES`, `WEB_INGRESS_TOKEN`, `RETRY_QUEUE_DIR`, `RETRY_INTERVAL_SECONDS`, `WEB_EVENT_MAX_RETRIES`, `WEB_EVENT_BACKOFF_BASE_S`, `ENV`, `LOG_LEVEL`, `LOG_DIR`, `LOG_SHIP_URL` (rpi5) / `INGRESS_TOKEN`, `ALLOWED_ORIGIN`, `LOG_LEVEL` (web).
- **모듈 결합도 개선**: 새로 만든 `rpi5/app/security.py`(인증/입력검증)와 `rpi5/app/retry_queue.py`(재시도 큐)는 각각 FastAPI 라우터(`detect.py`)와 독립된 모듈로 분리해 라우터가 직접 알 필요 없게 했습니다. `cloud/factory.py`에 `reset_provider_cache()`를 추가해 테스트가 provider 싱글턴 구현 세부사항에 의존하지 않도록 함.
  ```
  Before: routers/detect.py --(직접 os.getenv 산발적 참조)--> 환경
  After:  routers/detect.py --> app.security (인증/검증) --> app.config (단일 진입점) --> 환경
                             --> app.retry_queue (재시도) --> cloud.factory (Provider 추상화, 기존 유지)
  ```
- **환경별 설정 프로파일**: `AppConfig.env`(`development`/`staging`/`production`)가 `rpi5/app/logging_config.py`의 `_ENV_DEFAULT_LEVEL` 딕셔너리를 통해 기본 로그 레벨(개발=DEBUG, 그 외=INFO)을 결정. `LOG_LEVEL`을 명시하면 프로파일 기본값을 덮어씀. ESP32는 `esp32/include/config.h`의 `LOG_LEVEL`(0/1/2) 컴파일타임 매크로로 동일한 개념을 구현(`esp32/include/log.h`).

---

## 2. 예외 처리 및 안정성

### Before

- RPi5: `/api/v1/detect`에 인증·입력검증 없음(위 1번 참고). 클라우드 업로드가 실패하면 로그만 남기고 이미지가 영구 유실됨(`routers/detect.py`의 옛 `_handle_violation` — 실패 시 그냥 `status="failed"` 이벤트만 보내고 끝).
- 웹 대시보드로 보내는 이벤트(`rpi5/app/events.py`의 `_post()`)는 단발 시도 후 실패 시 폐기 — 재시도 없음.
- ESP32(`esp32/src/main.cpp`): 카메라 초기화 실패, 버퍼 할당 실패 시 `esp_restart()` 없이 LED만 깜빡이며 **무한 정지**(`setup()`의 `while(true){ledBlink(...)}` 3곳). 태스크 워치독(WDT)이 전혀 없어 `run_classifier()`나 HTTP 호출이 예기치 않게 멈춰도 자동 복구 수단이 없었음.

### After

- **RPi5 보안 계층 추가** (`rpi5/app/security.py`): `require_api_key()`(FastAPI `Depends`, `X-API-Key` 헤더를 `hmac.compare_digest`로 상수시간 비교, `DEVICE_API_KEY` 미설정 시 개발모드로 간주하고 `app/main.py` 시작 시 경고 로그), `validate_device_id()`(`^[A-Za-z0-9_-]{1,64}$` 화이트리스트 — path traversal 차단). `cloud/providers/local_mock.py`에도 방어적 경로 검증(`base not in dest.parents`)을 이중으로 추가.
- **업로드 검증** (`routers/detect.py`의 `detect()`): `len(image_bytes) > cfg.max_upload_bytes` → 413, `image.content_type not in ("image/jpeg","image/jpg")` → 400.
- **Graceful Degradation — 재시도 큐** (`rpi5/app/retry_queue.py`, 신규): 클라우드 업로드/저장이 실패하면 이미지+`ViolationRecord`를 `RETRY_QUEUE_DIR`(기본 `./data/retry_queue/<request_id>/`)에 즉시 디스크 저장(`enqueue()`) 후, `app/main.py`의 FastAPI `lifespan`에서 시작하는 백그라운드 루프(`run_forever()`, 기본 30초 간격)가 성공할 때까지 재시도(`_retry_once()`). 감지 파이프라인 자체는 `asyncio.create_task()`로 이미 완전히 비동기 분리되어 있었으므로(기존 설계), 이번 변경으로 "클라우드가 죽어도 감지는 계속되고, 증거도 잃지 않는다"가 완성됨.
  - 시나리오: 클라우드 업로드가 3연속 실패해도 → 이미지는 `data/retry_queue/`에 안전하게 남고, ESP32는 이미 200 OK를 받은 상태(감지 파이프라인 무중단), 30초마다 재시도되다가 클라우드가 복구되면 자동으로 `save_record()`까지 완료되고 큐에서 제거됨.
- **웹 이벤트 전송 재시도** (`rpi5/app/events.py`의 `_post()`): `WEB_EVENT_MAX_RETRIES`(기본 3회) + 지수 백오프(`WEB_EVENT_BACKOFF_BASE_S`, 기본 0.5s→1s→2s) 추가. 최종 실패는 여전히 폐기(의도적 설계 — 이 이벤트들은 실시간 텔레메트리이고, 증거 자체는 위의 retry_queue가 별도로 보장하므로 무한 큐잉하지 않음).
- **ESP32 자동 복구** (`esp32/src/main.cpp`): `fatalRestart()` 헬퍼 신규 추가 — 진단용 LED 점멸 후 `esp_restart()`. 카메라 초기화/버퍼 할당 실패 3곳 모두 무한루프 대신 이걸 호출하도록 변경. `esp_task_wdt_init(WATCHDOG_TIMEOUT_S, true)` + `esp_task_wdt_add(NULL)`를 `setup()`에 추가하고, `loop()` 최상단에 `esp_task_wdt_reset()` 추가(타임아웃 40초 — `HTTP_MAX_RETRIES` 3회 백오프 최악 케이스 ≈27.5초보다 여유 있게 설정, 근거는 `config.h.example` 주석에 명시).
- **웹 예외 처리** (`web/server.js`): `io.on('connection')` 콜백에 try-catch 추가(기존엔 없어서 콜백 내부 예외가 서버 전체를 죽일 수 있었음).

---

## 3. 성능 및 메모리 관리

### Before

- `rpi5/app/routers/detect.py`의 `detect()`는 `async def`였지만, 내부에서 `infer_ppe(img)`(ONNX Runtime `session.run` + OpenCV 전처리, 완전 동기 함수)를 **직접 호출**해 이벤트 루프를 블로킹하고 있었습니다. `uvicorn`도 워커 1개(기본값)라서 추론 중에는 다른 디바이스의 요청, `/health`, 백그라운드 이벤트 emit이 모두 지연됐습니다.
- 업로드/DB I/O(`cloud/providers/local_mock.py`, `supabase_provider.py`)는 이미 `asyncio.to_thread`로 잘 오프로드되어 있었음(이 부분은 기존에도 문제없음).
- 웹 대시보드는 이미 `MAX_HISTORY=50`으로 클라이언트 배열을 제한하고 있었고, 서버(`server.js`)는 상태를 전혀 들고 있지 않아(즉시 emit 후 버림) 메모리 누수 벡터가 없었음(기존에도 문제없음 — 이번에 변경 없음).

### After

- `routers/detect.py`: `result = await asyncio.to_thread(infer_ppe, img)`로 변경. onnxruntime의 `session.run()`과 OpenCV 연산은 GIL을 해제하므로, 워커 스레드로 넘기면 그동안 이벤트 루프가 다른 요청/백그라운드 태스크를 처리할 수 있습니다.
- **측정 필요**: 실제 지연시간/처리량 개선 폭은 이번 세션에서 실측하지 않았습니다(RPi5 실물 보드가 없어 PC에서 mock/단일 요청 기준 테스트만 수행). 측정 방법 제안: 동시 요청 2개 이상(`asyncio.gather` 또는 `hey`/`wrk` 같은 부하 도구)을 동시에 보내 `to_thread` 적용 전/후로 `/health` 응답 지연시간을 비교하면 이벤트 루프 블로킹 해소 효과를 정량화할 수 있습니다.
- 메모리 누수 관련: 이번 점검에서 새로 발견된 누적 구조는 없었습니다(재시도 큐는 디스크 기반이라 프로세스 메모리에 쌓이지 않음). `retry_queue`가 디스크에 무한정 쌓일 수 있는 점(장애가 길어질 경우)은 향후 과제로 `rpi5/README.md` 체크리스트에 기록했습니다.

---

## 4. 로깅

### Before

- `rpi5/app/main.py`에 `logging.basicConfig(level=INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")` 한 줄뿐. **`filename:lineno` 누락**, 로테이션 없음(컨테이너 stdout 의존), 로거별 레벨/`propagate` 명시 없음(암묵적으로 root에 의존).
- 웹(`web/server.js`)은 `console.log`/`console.error` 7곳뿐 — 레벨 구분, 타임스탬프 없음.
- ESP32는 `Serial.print*`가 전역에 산재, 컴파일타임 레벨 필터 없음 — `[Debug] box: ...`(매 감지 박스마다 출력) 같은 로그가 프로덕션 빌드에도 그대로 남음.
- 에러 로그에 `request_id`가 부분적으로 포함되어 있었으나(`detect.py`의 `logger.info`), 포맷 자체에 파일:줄번호가 없어 어디서 발생했는지는 로그 메시지 내용에만 의존.

### After

- **`rpi5/app/logging_config.py`(신규)**: `logging.config.dictConfig`로 root 로거에만 핸들러 부착(콘솔 + `RotatingFileHandler`). 포맷: `%(asctime)s %(levelname)s %(name)s %(filename)s:%(lineno)d: %(message)s` — 5요소(timestamp/level/logger name/file:line/message) 모두 포함. 로테이션: `maxBytes=10MB`, `backupCount=5` → **보관 상한 = 10MB × 6 = 60MB로 계산 가능**. 하위 모듈(`rpi5.detect`, `rpi5.events`, `rpi5.retry_queue`, `rpi5.main`)은 이름만 분리하고 `propagate` 기본값(True)에 의존 — 핸들러를 root에만 붙였으므로 중복 기록 없음.
- **중앙 로그 수집 훅**: `LOG_SHIP_URL` 설정 시 `logging.handlers.HTTPHandler`를 root에 추가로 붙여 매 로그 라인을 HTTP POST로 전송(Loki/ELK/CloudWatch 등 수집 엔드포인트를 가리키게 하면 됨). **측정/구축 필요**: 실제 수집 서버 연동은 인프라가 없어 이번 세션에서 검증하지 못했고, 훅만 제공했습니다.
- **웹**: `web/lib/logger.js`(신규, 외부 의존성 없이 JSON 라인 로거) 도입, `server.js`의 모든 `console.*` 호출을 `logger.info/warn/error`로 교체. `LOG_LEVEL` env로 `debug/info/warn/error` 필터링.
- **ESP32**: `esp32/include/log.h`(신규) — `LOG_LEVEL`(config.h) 컴파일타임 매크로로 `LOGE`/`LOGI`/`LOGD` 3단계. `LOGD`(디버그 박스 덤프)는 `LOG_LEVEL=1`(필드 배포 권장값)에서 바이너리에서 아예 제거됨(런타임 필터링이 아니라 `#if`로 컴파일 자체에서 빠짐).
- **역추적 컨텍스트 Before/After 예시** (`routers/detect.py`):
  - Before: `logger.exception("Cloud storage upload/save failed for request_id=%s", result.request_id)` — request_id는 있었지만 스택트레이스 위치 정보(file:line)가 로그 포맷 자체엔 없었음.
  - After: 동일 로그 메시지가 이제 `2026-08-31 12:00:00,000 ERROR rpi5.detect detect.py:170: Cloud storage upload/save failed for request_id=... — queuing for retry` 형태로 출력됨(파일:줄번호 자동 포함) + 큐잉 여부까지 메시지에 명시.

---

## 5. CI/CD 자동화 파이프라인 (GitHub Actions + Pytest)

`.github/workflows/ci.yml` (신규) 기준:

| 단계 | 구현 내용 | 게이트/조건 |
|---|---|---|
| 1. Code Push | main/feature 브랜치 전략은 기존 그대로(강제하지 않음) | - |
| 2. GitHub Actions 트리거 | `on: push (branches: [main])`, `pull_request (branches: [main])`, `workflow_dispatch` | `concurrency: {group: ci-${{github.workflow}}-${{github.ref}}, cancel-in-progress: true}`로 같은 ref의 중복 실행(같은 커밋이 push+PR 양쪽에서 트리거되는 경우) 자동 취소 |
| 3. Pytest 자동 테스트 | `test` job 안에 **"Unit tests"**(`pytest tests/unit -v`)와 **"Integration tests"**(`pytest tests/integration -v`) 2개의 별도 이름 step으로 구성 — Actions UI에서 어느 종류가 실패했는지 바로 구분됨 | `lint` job(`ruff check .`)이 먼저 통과해야 `needs: lint`로 실행됨 |
| 4. Build & Deploy | `build` job: `docker build -f rpi5/Dockerfile -t ppe-rpi5:${{github.sha}} .` (repo root 컨텍스트, Dockerfile 주석과 일치) + `web-build` job에서 검증한 `npm run build` 재확인 | `needs: [test, web-build]` + `if: github.event_name == 'push' && github.ref == 'refs/heads/main'` — PR에서는 아예 실행되지 않고, main push라도 테스트 실패 시 **skip**(실패 아님) 처리됨 |

- **테스트 실패 시 빌드가 스킵되는 근거**: GitHub Actions는 `needs`로 지정된 job이 실패하면 그 job에 의존하는 job을 기본적으로 **skipped** 상태로 표시하고 실행하지 않습니다(추가 `if` 조건 없이도 보장되는 기본 동작). `build` job은 `needs: [test, web-build]`이므로 pytest가 하나라도 실패하면 Docker 빌드 자체가 시도되지 않습니다.
- **matrix 미사용**: Python 3.11 / Node 20 단일 조합만 검증(RPi5는 실제 배포 대상이 이 버전 하나이므로 조합을 늘릴 이유가 없음 — 불필요한 실행 비용 회피).
- **실제 배포 대상 부재**: 이 프로젝트는 아직 실제 배포용 레지스트리/서버가 없어 `build` job은 "이미지가 빌드되는가"까지만 검증합니다. 실제 배포를 추가한다면 `environment: production` + 필수 리뷰어 게이트, `secrets.REGISTRY_TOKEN` 기반 `docker push`를 이 job 뒤에 추가하면 됩니다(주석으로 `ci.yml`에 남겨둠).
- **부가 발견 및 수정**: `web/package.json`의 `lint` 스크립트(`next lint`)가 ESLint 설정 부재로 **CI에서 무한 대기(대화형 프롬프트)** 하는 문제를 실제로 재현·확인했습니다 — `web/.eslintrc.json`(신규, `next/core-web-vitals`)을 추가해 해결. 별도 `esp32-build` job도 추가해 `pio run`으로 펌웨어가 실제로 컴파일되는지 검증(Edge Impulse SDK가 CI에 없으므로 vendored 라이브러리 존재 여부를 먼저 체크하고 없으면 경고와 함께 스킵).

파이프라인 전체 흐름:

```
Push/PR ──▶ GitHub Actions 트리거
              │
              ▼
            lint (ruff)
              │  (실패 시 이후 전부 skip)
              ▼
   ┌──────────┴──────────┐
   ▼                     ▼
 test                web-build
 (Unit → Integration)  (npm ci/lint/build)
   │                     │
   └──────────┬──────────┘
              ▼
   build  (push to main만, Docker 이미지 빌드 검증)
```

---

## 리포트 마무리

### 1. 변경사항 요약

| 항목 | 주요 변경 | 영향받은 파일 수 |
|---|---|---|
| 파라미터화/가독성 | `config.py` env-override 재설계, 신규 설정 11개(rpi5) + 3개(web) 추가 | 4 (`rpi5/app/config.py`, `.env`, `.env.example`×2) |
| 예외 처리/안정성 | 인증·입력검증·path traversal 방어, 재시도 큐, ESP32 워치독/자동재부팅 | 7 (`security.py`, `retry_queue.py`, `detect.py`, `events.py`, `local_mock.py`, `main.cpp`, `main.py`) |
| 성능/메모리 | ONNX 추론 `asyncio.to_thread` 오프로드 | 1 (`routers/detect.py`) |
| 로깅 | 구조화 로깅 3개 언어(Python dictConfig, JS 커스텀 로거, C++ 매크로) | 5 (`logging_config.py`, `main.py`, `server.js`, `logger.js`, `log.h`) |
| CI/CD | GitHub Actions 4단계 파이프라인 신규, ESLint 설정 신규, pytest 35개 신규 | 9 (`ci.yml`, `.eslintrc.json`, 테스트 파일 6개, `ruff.toml`) |

### 2. 향후 과제

- 성능 개선 효과 실측(동시 요청 부하 테스트) — 이번엔 방법만 제안, 실측은 못함
- `LOG_SHIP_URL` 훅에 실제 중앙 로그 수집 서버(Loki/ELK/CloudWatch) 연동 및 검증
- `retry_queue`(`rpi5/data/`) 디스크 사용량 상한/보관 정책 추가
- `next@14.2.35`의 `npm audit` High severity CVE 다수 → 16.x 메이저 업그레이드(breaking change, 별도 작업 필요)
- 다중 인물 프레임 개별 PPE 판정, 실제 RPi5 보드 성능 튜닝 (기존부터 있던 항목)
- 웹 대시보드(Jest) 테스트 스위트는 이번 범위에서 다루지 않음 — pytest(RPi5)만 addendum 13번이 명시한 CI 게이트로 구성

### 3. README 개발 일지

`README.md`의 "개발 일지" 섹션에 2026-08-31 날짜로 이번 변경사항 요약을 이미 추가했습니다(리포트 전체를 옮기지 않고 핵심만 압축).
