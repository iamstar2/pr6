# cloud/ — 위반 이미지·기록 저장 (Provider 패턴)

> ⚠️ **이 폴더는 GitHub에 올라가지 않습니다** (`.gitignore`로 제외됨). ③클라우드 저장은
> 팀원이 별도로 새로 구현하기로 했고, 여기 있는 건 로컬 테스트/참고용 구현체입니다. 팀원이
> 지켜야 할 계약(RPi5→웹 이벤트 등)은 저장소 루트의 [`INTEGRATION.md`](../INTEGRATION.md) 참고.

위반(`violation == true`)이 발생했을 때만 RPi5 파이프라인이 호출하는 저장 계층입니다.
실제 클라우드 계정 없이도 `LocalMockStorageProvider`로 전체 파이프라인을 테스트할 수 있고,
`CLOUD_PROVIDER=supabase`로 바꾸면 실제 Supabase Storage/DB에 저장됩니다.

## 구조

```
cloud/
  base.py                    CloudStorageProvider(ABC) — upload_image / save_record
  schemas.py                 ViolationRecord
  factory.py                 CLOUD_PROVIDER 환경변수로 provider 인스턴스 생성
  providers/
    local_mock.py            구현 완료 — 로컬 디스크에 저장 (기본값, 계정 불필요)
    supabase_provider.py     구현 완료 — Supabase Storage + Postgres 테이블
    remote_stub.py           TODO 스켈레톤 — AWS/GCP/Firebase 등 다른 프로바이더 추가 시 참고
  supabase_schema.sql        Supabase에서 한 번 실행할 테이블 생성 SQL
  .env.example
```

## Supabase 사용하기 (구현 완료)

실제 값은 **`rpi5/.env`** 한 곳에만 넣으면 됩니다 (`cp rpi5/.env.example rpi5/.env` 후 편집 —
`cloud/factory.py`가 자동으로 로드합니다). `cloud/.env.example`은 이 모듈이 필요로 하는
환경변수 목록 문서 역할입니다.

1. https://supabase.com 에서 프로젝트 생성.
2. **Storage** → New bucket → 이름 `violations` (기본값, `SUPABASE_BUCKET`으로 바꿀 수 있음) →
   **Public bucket** 켜기 (이 provider는 `get_public_url()`로 URL을 만들기 때문에 public이
   가장 간단합니다. private로 쓰려면 `supabase_provider.py`의 `upload_image`를
   `create_signed_url()`로 바꾸세요).
3. **SQL Editor** → `cloud/supabase_schema.sql` 내용을 붙여넣고 실행 → `violation_records`
   테이블 생성.
4. **Project Settings → API** → `Project URL`과 `service_role` 키를 복사.
   (`service_role` 키는 RLS를 무시하고 서버에서만 써야 하는 비밀 키입니다 — 절대 브라우저/ESP32
   등 클라이언트에 넣지 마세요. RPi5 서버 프로세스에서만 사용됩니다.)
5. `rpi5/.env`에 반영:
   ```
   CLOUD_PROVIDER=supabase
   SUPABASE_URL=https://your-project-ref.supabase.co
   SUPABASE_KEY=<service_role 키>
   SUPABASE_BUCKET=violations
   SUPABASE_TABLE=violation_records
   ```
6. RPi5 서버 재시작 — 이제 위반 발생 시 이미지가 Supabase Storage에, 기록이 테이블에 실제로
   저장됩니다. (이번 세션은 실제 Supabase 프로젝트/키가 없어서 라이브로 검증하지 못했습니다 —
   `local_mock`과 동일한 인터페이스라 코드 경로는 같지만, 처음 연결할 때 버킷 이름/키 오탈자를
   한 번 확인해보세요.)

## 사용하는 쪽 (RPi5) 코드

```python
from cloud.factory import get_storage_provider
from cloud.schemas import ViolationRecord

provider = get_storage_provider()
image_url = await provider.upload_image(jpeg_bytes, key=f"{device_id}/{request_id}.jpg")
await provider.save_record(ViolationRecord(
    id=request_id, device_id=device_id, timestamp=timestamp,
    helmet_detected=False, vest_detected=True,
    image_url=image_url, violation_type="no_helmet",
))
```

## 다른 프로바이더 추가 가이드 (AWS/GCP/Firebase 등, Supabase 외에 필요해지면)

1. `providers/remote_stub.py`를 복사해 `providers/aws_s3.py` (또는 `gcs.py` / `firebase.py`)로 이름을 바꾼다.
2. `__init__`에서 SDK 클라이언트를 초기화한다. 자격 증명은 `.env.example`에 항목을 추가하고 코드는 `os.getenv(...)`로 읽는다 — 하드코딩 금지.
3. `upload_image`: bytes를 업로드하고 접근 가능한 URL(퍼블릭 또는 서명 URL)을 반환하도록 구현한다.
4. `save_record`: `ViolationRecord`를 DB(DynamoDB / Firestore / Cloud SQL 등)에 저장하도록 구현한다.
5. `factory.py`의 `get_storage_provider()`에 `elif name == "aws_s3": _provider = S3StorageProvider()` 형태로 등록한다.
6. `CLOUD_PROVIDER=aws_s3` 로 환경변수를 바꾸면 RPi5 쪽 코드는 한 줄도 수정할 필요가 없다 (Provider 패턴의 목적).

## 저장 완료/실패 알림

`cloud_upload_status` WebSocket 이벤트는 이 모듈이 직접 보내지 않습니다 — 이 모듈은 순수 저장
로직(Provider)만 담당하고, `upload_image`/`save_record`를 호출한 **RPi5 파이프라인**이 성공/실패
결과를 보고 웹 백엔드로 이벤트를 전송합니다 (`rpi5/app/events.py` 참고).
