// Minimal shape checks for the payloads RPi5 posts to /api/events/* (see
// INTEGRATION.md section 2). Deliberately not a full schema library — just
// enough to reject junk before it's broadcast verbatim to every connected
// browser (the previous behavior: whatever JSON parsed, forwarded as-is).
function isString(v) {
  return typeof v === 'string';
}
function isBoolean(v) {
  return typeof v === 'boolean';
}
function isFiniteNumber(v) {
  return typeof v === 'number' && Number.isFinite(v);
}

const FRAME_EVENT_SPEC = {
  request_id: isString,
  device_id: isString,
  timestamp: isString,
  helmet_detected: isBoolean,
  vest_detected: isBoolean,
  violation: isBoolean,
  confidence: isFiniteNumber,
};

const CLOUD_STATUS_SPEC = {
  request_id: isString,
  device_id: isString,
  status: (v) => v === 'success' || v === 'failed',
  timestamp: isString,
};

function validate(payload, spec) {
  if (!payload || typeof payload !== 'object') {
    return 'Payload must be a JSON object';
  }
  for (const [field, check] of Object.entries(spec)) {
    if (!check(payload[field])) {
      return `Invalid or missing field "${field}"`;
    }
  }
  return null;
}

// eventName is the Socket.IO event this payload is about to be re-broadcast as
// (see server.js's ROUTES table) — cloud_upload_status has a different shape
// than the two frame events.
function validateEventPayload(eventName, payload) {
  const spec = eventName === 'cloud_upload_status' ? CLOUD_STATUS_SPEC : FRAME_EVENT_SPEC;
  return validate(payload, spec);
}

module.exports = { validateEventPayload };
