-- Run once in the Supabase project's SQL editor (Database -> SQL Editor -> New query).
-- Matches cloud/schemas.py::ViolationRecord exactly.

create table if not exists violation_records (
  id              text primary key,          -- RPi5 request_id
  device_id       text not null,
  timestamp       timestamptz not null,
  helmet_detected boolean not null,
  vest_detected   boolean not null,
  image_url       text not null,
  violation_type  text not null,
  created_at      timestamptz not null default now()
);

-- Row Level Security is on by default for new tables. If you connect with the
-- service_role key (server-side only, e.g. from rpi5/) it bypasses RLS entirely —
-- that's the intended setup here. If you instead use the anon key, add a policy, e.g.:
--
-- alter table violation_records enable row level security;
-- create policy "allow inserts from server" on violation_records
--   for insert to anon with check (true);
