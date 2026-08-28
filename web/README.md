# IoT 안전 위반 모니터링 웹 대시보드 (`web/`)

Frontend (실시간 모니터링 UI) + Socket.IO 릴레이 백엔드. `rpi5/` 로부터 HTTP POST 이벤트를
받아 연결된 모든 브라우저에 Socket.IO로 재전송(broadcast)한다.

## 기술 스택 & 선택 이유

- **Next.js (App Router)** — `claude_code_prompt.md` 4.4절에서 추천한 스택. React 기반으로
  실시간 UI 컴포넌트(라이브 오버레이, 토스트, 이력 리스트)를 빠르게 구성할 수 있고, 서버
  렌더링/정적 빌드 파이프라인이 검증되어 있어 배포가 단순하다.
- **Tailwind CSS** — 유틸리티 클래스 + CSS 커스텀 프로퍼티(`--color-*`) 조합으로
  `DESIGN.md`의 시맨틱 디자인 토큰을 그대로 매핑했다. 컴포넌트 마크업은 테마와 무관하게
  동일하게 유지되고, 토큰 값만 `data-theme` 속성에 따라 바뀐다.
- **Socket.IO (서버 + 클라이언트)** — 브라우저와의 실시간 양방향 채널이 필요하고, WebSocket이
  막힌 네트워크에서도 폴링으로 자동 폴백해준다. `rpi5`가 보내는 이벤트를 그대로 재전송하는
  용도로는 순수 `ws`보다 재연결/룸 관리가 쉬운 Socket.IO가 적합하다.
- **커스텀 `server.js` (Node `http` + Next.js + Socket.IO)** — Socket.IO는 지속적으로 열려있는
  HTTP 서버 인스턴스에 붙어 연결된 클라이언트 목록을 유지해야 하는데, Next.js의 API Routes는
  요청마다 Next 내부 서버가 처리하기 때문에 Socket.IO를 붙일 서버 핸들을 안정적으로 공유할
  수 없다. 그래서 `server.js`에서 직접 `http.createServer`를 만들고, `/api/events/*` 세 경로는
  거기서 바로 처리(JSON 파싱 → `io.emit`)하고, 나머지 모든 요청은 Next의 요청 핸들러로
  넘긴다. 페이지/정적 자산 렌더링은 Next가, 실시간 소켓 브로드캐스트는 같은 프로세스의
  Socket.IO 서버가 담당하는 구조다.
- **JavaScript (TypeScript 미사용)** — 이 모듈의 데이터 계약(payload shape)이 이미 프롬프트에
  JSON 스키마로 고정되어 있고, 컴포넌트 수가 많지 않아 타입 시스템 없이도 계약을 지키기
  쉽다고 판단해 순수 JS로 구현 속도를 우선했다. (JSDoc 등으로 언제든 타입을 점진적으로
  추가할 수 있는 구조.)

## 디렉터리 구조

```
web/
├── server.js              # 커스텀 서버: Next 렌더링 + Socket.IO + /api/events/* 인그레스
├── app/
│   ├── layout.js           # 루트 레이아웃, 테마 FOUC 방지 인라인 스크립트
│   ├── page.js             # 대시보드 메인 (소켓 연결, 상태관리)
│   └── globals.css         # DESIGN.md 토큰 → CSS 커스텀 프로퍼티, 라이트/다크 세트
├── components/
│   ├── LiveDetectionView.js # 요구사항 1: bbox 오버레이 (SVG)
│   ├── ViolationToast.js    # 요구사항 2: 위반 토스트/배너
│   ├── SoundToggle.js       # 요구사항 2: 알림음 on/off (localStorage 저장)
│   ├── ViolationHistory.js  # 요구사항 3/4: 이력 리스트 + 저장상태 뱃지 + 썸네일
│   └── ThemeToggle.js       # 요구사항 5: 라이트/다크 테마 토글 (localStorage 저장)
├── lib/
│   ├── socket.js            # 싱글턴 Socket.IO 클라이언트 (NEXT_PUBLIC_SOCKET_URL)
│   ├── beep.js               # Web Audio API로 합성한 알림 비프음 (외부 파일 없음)
│   └── time.js                # "n초 전" 상대 시간 포맷터
├── scripts/
│   └── simulate-events.sh    # rpi5/esp32 없이 3개 인그레스 엔드포인트에 curl로 샘플 이벤트 전송
├── .env.example
└── package.json
```

## 통합 계약 (rpi5 ↔ web)

`rpi5/app/events.py` 가 그대로 호출하는 엔드포인트/이벤트 이름이므로 변경하지 않았다:

| HTTP 인그레스 (rpi5 → web) | 재전송되는 Socket.IO 이벤트 | Payload |
|---|---|---|
| `POST /api/events/live-frame` | `live_detection_frame` | PPEResult + `image_base64`/`image_width`/`image_height` |
| `POST /api/events/violation` | `violation_detected` | 위와 동일 (이미지 포함) |
| `POST /api/events/cloud-status` | `cloud_upload_status` | 업로드 상태 (그대로 전달) |

모든 엔드포인트는 어떤 오리진에서 온 요청이든 허용하는 CORS(`Access-Control-Allow-Origin: *`)를
붙여서 응답한다 (개발/모킹 단계용). 서버는 `PORT` 환경변수(기본 `4000`)로 리슨한다.

### 실시간 화면 = 실제 캡처 이미지 (연속 스트리밍 아님)

ESP32는 사람을 감지할 때마다(위반 여부와 무관하게) 고해상도 이미지 1장을 이미 RPi5로
보내고 있다. RPi5는 그 이미지를 그대로 base64로 인코딩해 `live_detection_frame` /
`violation_detected` 이벤트에 실어 웹으로도 보낸다 — ESP32 입장에서는 추가 전송이 전혀
없으므로(이미 보내던 이미지를 RPi5가 한 번 더 릴레이하는 것) 공짜다. 실제 이미지 픽셀
크기(`image_width`/`image_height`)도 같이 보내주기 때문에, `components/LiveDetectionView.js`는
그 값으로 SVG `viewBox`를 맞춰서 bbox를 실제 이미지 위에 정확히 겹쳐 그린다 (이전처럼
640x480을 가정할 필요 없음). 다만 이건 ESP32가 감지할 때마다 갱신되는 스냅샷이지, 연속
비디오 스트림이 아니다 — ESP32가 이미 캡처 쿨다운(`CAPTURE_COOLDOWN_MS`, 기본 5초)을 두고
있어서 그 주기로만 화면이 갱신된다.

## 실행 방법

### 1. 설치

```bash
cd web
npm install
```

### 2. 환경변수

`.env.example` 을 `.env.local` 로 복사 후 필요시 값 수정:

```bash
cp .env.example .env.local
```

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PORT` | `4000` | `server.js` (Next + Socket.IO + 인그레스)가 리슨하는 포트. rpi5의 `web_backend_url` 이 이 포트를 가리켜야 한다. |
| `NEXT_PUBLIC_SOCKET_URL` | `http://localhost:4000` | 브라우저의 Socket.IO 클라이언트가 접속할 주소. 브라우저에서 접근 가능한 호스트/포트여야 한다 (서버 전용 환경변수가 아님, `NEXT_PUBLIC_` 접두사로 클라이언트 번들에 인라인됨). |

### 3. 개발 모드

```bash
npm run dev
```

`http://localhost:4000` 에서 대시보드가 뜬다 (Next.js dev 서버 + Socket.IO가 같은 프로세스,
같은 포트에서 동작).

### 4. 프로덕션 빌드 & 실행

```bash
npm run build
npm start
```

## 파이프라인 없이 대시보드 단독 테스트하기

rpi5/esp32를 켜지 않고도 UI를 눈으로 검증할 수 있도록 `scripts/simulate-events.sh` 를
포함했다. 서버가 떠 있는 상태(`npm run dev` 또는 `npm start`)에서:

```bash
bash scripts/simulate-events.sh
# 또는 다른 포트/호스트로 띄웠다면:
BASE_URL=http://localhost:4000 bash scripts/simulate-events.sh
```

curl로 실제 세 인그레스 엔드포인트에 순서대로 POST한다:
1. 정상(위반 아님) `live-frame`
2. 위반 이벤트 #1 (헬멧 미착용, `esp32-01`)
3. #1에 대한 `cloud-status` 성공
4. 위반 이벤트 #2 (조끼 미착용, `esp32-02`)
5. #2에 대한 `cloud-status` 실패

브라우저에서 대시보드를 열어둔 상태로 실행하면: 두 개의 위반 토스트가 뜨고, 이력 리스트에
2건이 추가되며 각각 "저장 완료" / "저장 실패" 뱃지가 표시되고, 라이브 오버레이가 마지막
이벤트의 bbox를 그린다.

## 실제로 검증한 것 (이번 세션에서 수행한 확인)

- `npm install` — Node v24.19.0 / npm 11.17.0 환경에서 정상 설치 (`next`는 알려진 취약점 때문에
  `14.2.5` → `14.2.35`로 올려서 설치함; 남은 `npm audit` 경고 2건은 Next.js가 내부적으로
  번들링한 postcss/Server Actions 관련 항목으로, 이 프로젝트는 Server Actions(`'use server'`)를
  사용하지 않으므로 실질적 영향 없음).
- `npm run build` — 정상적으로 컴파일/정적 페이지 생성 완료 (`✓ Compiled successfully`).
- `npm start` (프로덕션) 및 `npm run dev` (개발) 둘 다 기동 후 `GET /` 가 200과 함께
  대시보드 HTML(제목/섹션 텍스트 포함)을 반환하는 것을 curl로 확인.
- `GET /healthz` 로 서버 자체 상태(연결된 소켓 수) 확인 가능함을 검증.
- `scripts/simulate-events.sh` 를 서버가 켜진 상태에서 실행하고, 별도의 Node
  `socket.io-client` 스크립트로 세 이벤트(`live_detection_frame`, `violation_detected`,
  `cloud_upload_status`)가 정확히 전송한 JSON body 그대로 5건 모두 수신되는 것을 확인함
  (서버 로그에도 각 이벤트 수신이 `request_id`와 함께 기록됨).
- CORS: `OPTIONS`/`POST` 요청에 `Access-Control-Allow-Origin: *` 헤더가 붙는 것을 curl로 확인.
- 브라우저 자동화 도구가 없는 환경이라, 실제 브라우저에서의 화면 렌더링(테마 토글 클릭,
  토스트 애니메이션, 알림음 재생 등)은 육안으로 직접 확인하지 못했다 — 대신 SSR HTML에
  각 컴포넌트의 텍스트가 정상적으로 포함되어 있는지, 그리고 소켓 이벤트가 브라우저 클라이언트와
  동일한 라이브러리(`socket.io-client`)로 정상 수신되는지까지 확인했다.
