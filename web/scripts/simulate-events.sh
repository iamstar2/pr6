#!/usr/bin/env bash
# Posts a few sample payloads straight at this dashboard's own ingress
# endpoints, so the UI can be exercised end-to-end without rpi5/esp32
# running at all. Requires curl (present on any normal dev machine / WSL /
# git-bash) and the server (`npm run dev` or `npm start`) already running.
#
# Usage:
#   bash web/scripts/simulate-events.sh
#   BASE_URL=http://localhost:4000 bash web/scripts/simulate-events.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:4000}"

post() {
  local path="$1"
  local body="$2"
  echo "--> POST ${BASE_URL}${path}"
  curl -sS -X POST "${BASE_URL}${path}" \
    -H "Content-Type: application/json" \
    -d "${body}" \
    -w "\n    (HTTP %{http_code})\n"
}

now_iso() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

REQ_ID_1="$(date +%s)-violation-1"
REQ_ID_2="$(date +%s)-violation-2"

echo "== 1) live detection frame (no violation) =="
post "/api/events/live-frame" "$(cat <<JSON
{
  "request_id": "${REQ_ID_1}-frame",
  "device_id": "esp32-01",
  "timestamp": "$(now_iso)",
  "helmet_detected": true,
  "vest_detected": true,
  "violation": false,
  "confidence": 0.94,
  "bbox": [180.0, 90.0, 140.0, 260.0],
  "image_ref": "mock-not-a-url"
}
JSON
)"

sleep 1

echo "== 2) violation detected (helmet missing) =="
post "/api/events/violation" "$(cat <<JSON
{
  "request_id": "${REQ_ID_1}",
  "device_id": "esp32-01",
  "timestamp": "$(now_iso)",
  "helmet_detected": false,
  "vest_detected": true,
  "violation": true,
  "confidence": 0.87,
  "bbox": [120.5, 60.0, 160.0, 240.0],
  "image_ref": "mock-not-a-url"
}
JSON
)"

sleep 1

echo "== 3) cloud upload status: success (matches violation 1) =="
post "/api/events/cloud-status" "$(cat <<JSON
{
  "request_id": "${REQ_ID_1}",
  "device_id": "esp32-01",
  "status": "success",
  "image_url": "http://localhost:8000/mock-media/esp32-01/${REQ_ID_1}.jpg",
  "timestamp": "$(now_iso)"
}
JSON
)"

sleep 1

echo "== 4) violation detected (vest missing) =="
post "/api/events/violation" "$(cat <<JSON
{
  "request_id": "${REQ_ID_2}",
  "device_id": "esp32-02",
  "timestamp": "$(now_iso)",
  "helmet_detected": true,
  "vest_detected": false,
  "violation": true,
  "confidence": 0.79,
  "bbox": [200.0, 40.0, 130.0, 250.0],
  "image_ref": "mock-not-a-url"
}
JSON
)"

sleep 1

echo "== 5) cloud upload status: failed (matches violation 2) =="
post "/api/events/cloud-status" "$(cat <<JSON
{
  "request_id": "${REQ_ID_2}",
  "device_id": "esp32-02",
  "status": "failed",
  "image_url": "",
  "timestamp": "$(now_iso)"
}
JSON
)"

echo ""
echo "Done. Open the dashboard to see: 2 history entries (one 저장 완료, one 저장 실패),"
echo "toasts for both violations, and the live overlay reflecting the last event."
