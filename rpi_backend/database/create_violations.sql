-- PPE 미착용 이벤트를 저장하는 테이블.
-- Supabase SQL Editor에서 그대로 실행하면 된다.

create table if not exists violations (
    id uuid primary key default gen_random_uuid(),

    -- 서버가 이벤트를 기록한 시각
    created_at timestamptz not null default now(),

    -- ESP32가 촬영한 시각 (헤더로 전달되지 않으면 null)
    captured_at timestamptz null,

    -- 어떤 카메라/디바이스에서 발생했는지
    device_id text not null,

    -- 이 이벤트에서 검출된 미착용 종류 목록 (예: {NO_HARDHAT, NO_SAFETY_VEST})
    violation_types text[] not null,

    -- 미착용 detection 중 가장 높은 confidence
    max_confidence float not null,

    -- 전체 detection 결과 (class_name, violation_type, confidence, bbox 포함)
    detections jsonb not null,

    -- Supabase Storage 상의 이미지 경로 (violations/YYYY/MM/DD/<UUID>.jpg)
    image_path text not null,

    -- 어떤 모델이 판정했는지 (모델 교체 이력 추적용)
    model_name text not null,
    model_version text null
);

-- 웹 갤러리는 최신순으로 조회하므로 created_at 인덱스가 중요하다.
create index if not exists idx_violations_created_at
    on violations (created_at desc);

-- 특정 카메라(device)의 위반 이력만 조회할 때 사용
create index if not exists idx_violations_device_id
    on violations (device_id);
