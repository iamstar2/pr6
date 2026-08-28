# 클론 후 설정 가이드 (①ESP32 / ④웹 담당 팀원용)

이 저장소엔 `esp32/`와 `web/`만 들어있습니다 (②RPi5/③클라우드는 별도 구현 — 계약은
[`INTEGRATION.md`](INTEGRATION.md) 참고). 클론 직후 두 가지가 비어있는 상태입니다:
`esp32/lib/`(용량 때문에 제외됨)와 `esp32/include/config.h`(개인 설정값이라 제외됨).

**Claude Code에게 맡기는 경우**: 이 문서를 그대로 프롬프트로 사용해도 됩니다 — "SETUP.md 보고
세팅해줘"라고 하면 아래 순서대로 실행하면 됩니다.

## 0. 사전 설치

- Node.js 18 이상
- Python 3.11 이상
- **PlatformIO** (Arduino IDE는 쓰지 않습니다):
  - VSCode 확장으로 설치: Extensions(Ctrl+Shift+X) → "PlatformIO IDE" 검색 → 설치 → VSCode 재시작.
  - 또는 CLI만: `pip install platformio` (설치 직후엔 새 터미널을 열어야 `pio` 명령이 PATH에 잡힙니다).
  - 확인: `pio --version`

## 1. ESP32 — Edge Impulse 모델 설치

`esp32/lib/`가 비어있을 겁니다 (Edge Impulse SDK가 ~24MB라 저장소에서 뺐습니다). 같은 FOMO
사람 감지 모델을 Edge Impulse Studio에서 Arduino 라이브러리(zip)로 export해서 받으세요
(프로젝트 → Deployment → Create Library → **Arduino library** 선택 → Build).

zip을 받았으면:
```bash
python esp32/scripts/install_ei_model.py 다운받은-zip-경로.zip
```
이 스크립트가 알아서: 압축 해제 → `esp32/lib/`에 복사 → 용량 절약을 위해 `examples/` 삭제 →
`esp32/src/main.cpp`의 `#include` 헤더명이 새 라이브러리와 일치하는지 확인해서 안 맞으면
경고까지 해줍니다.

수동으로 하고 싶다면: zip 압축 해제 → 최상위 `<ProjectName>_inferencing/` 폴더를 통째로
`esp32/lib/`에 복사 → `examples/` 삭제(선택) → `esp32/src/main.cpp` 상단의
`#include <...>`를 새 라이브러리의 헤더 파일명(`esp32/lib/<ProjectName>_inferencing/src/*.h`)과
맞춘다.

## 2. ESP32 — 개인 설정값 채우기

```bash
cd esp32
cp include/config.h.example include/config.h
```
`config.h`를 열어서 채우세요:
- `WIFI_SSID` / `WIFI_PASSWORD` — 본인 Wi-Fi
- `SERVER_BASE_URL` — 본인이 구현한 RPi5 서버의 주소 (예: `http://192.168.0.10:8000`) —
  ESP32와 그 서버가 반드시 같은 네트워크(같은 공유기 Wi-Fi)에 있어야 합니다.
- `DEVICE_ID` — 카메라 노드 식별자 (여러 대 쓸 경우 겹치지 않게)

## 3. ESP32 — 빌드 확인 & 업로드

```bash
cd esp32
pio run              # 빌드만
pio run -t upload    # 보드 USB 연결 후 업로드
pio device monitor -b 115200   # 로그 확인
```
VSCode에서는 하단 상태바의 체크(✓)=Build, 화살표(→)=Upload, 플러그(🔌)=Monitor 아이콘으로도
동일하게 실행할 수 있습니다.

### 자주 발생하는 문제

- **포트가 안 보임 / 업로드 타임아웃**: XIAO ESP32S3는 USB CDC라 보통 드라이버 없이 인식되지만
  안 되면 CP210x/CH340 드라이버 확인. 자동 인식이 안 되면 `platformio.ini`에
  `upload_port = COM5` / `monitor_port = COM5` 직접 지정 (Windows: 장치관리자 → 포트).
- **`Error: app partition is too small`**: `platformio.ini`에 이미 `board_build.partitions =
  huge_app.csv`가 설정되어 있음. 그래도 부족하면 `-DCORE_DEBUG_LEVEL`을 낮추거나 파티션
  테이블을 더 조정.
- **`Camera init failed: 0x105`**: PSRAM 미인식. `board_build.psram_type = opi` +
  `-DBOARD_HAS_PSRAM`이 `platformio.ini`에 있는지 확인. PSRAM 없는 보드라면
  `CAMERA_FB_IN_PSRAM`을 `CAMERA_FB_IN_DRAM`으로, 캡처 해상도도 낮춰야 함.
- **`undefined reference to ...` (링크 에러)**: 라이브러리 교체(1번) 후 캐시가 꼬인 경우 —
  `pio run -t clean` 후 재빌드.
- **Wi-Fi는 되는데 서버 전송이 계속 실패**: `config.h`의 `SERVER_BASE_URL`이 본인 RPi5 서버의
  실제 IP:포트인지 확인, 방화벽에서 해당 포트 인바운드가 막혀있지 않은지 확인.

## 4. 웹 대시보드

```bash
cd web
npm install
cp .env.example .env.local   # 기본값(localhost:4000)으로 충분하면 안 바꿔도 됨
npm run dev                   # http://localhost:4000
```
기술 스택/통합 계약/단독 테스트 방법은 [`web/README.md`](web/README.md).

## 5. RPi5/클라우드는 직접 구현

이 저장소엔 없습니다. ESP32가 뭘 보내는지, 웹이 뭘 기대하는지는 [`INTEGRATION.md`](INTEGRATION.md)에
정리되어 있습니다 — 그 계약만 지키면 ESP32/웹 코드는 안 건드려도 됩니다.

## 6. 끝까지 됐는지 확인

- `esp32`: `pio run` 성공 + 실제 보드 업로드 후 시리얼 로그에 Wi-Fi 연결 확인
- `web`: `npm run dev` 실행 후 브라우저에서 `http://localhost:4000` 접속되고 화면 뜨는지 확인
- 본인의 RPi5 서버를 띄운 뒤, ESP32 앞에 사람을 비춰서 웹 대시보드에 실시간 화면/알림이
  뜨는지 최종 확인
