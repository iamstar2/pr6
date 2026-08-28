/* ESP32-S3 person detection + capture node
 *
 * Board: Seeed XIAO ESP32S3 Sense (OV2640, 8MB PSRAM)
 * Model: Edge Impulse FOMO person-detection, 64x64 RGB (lib/Person_detection_FOMO_inferencing)
 *
 * Pipeline:
 *   1. Every cycle, capture ONE JPEG frame at a fixed resolution (CAPTURE_FRAMESIZE in
 *      config.h) -> decode to RGB888 -> resize to the model's 64x64 input -> run the
 *      FOMO classifier. The raw JPEG bytes are kept around for step 2 (no second
 *      capture, no on-the-fly resolution switch — an earlier version tried switching
 *      to a bigger resolution only when uploading, but esp_camera_fb_get() kept
 *      returning NULL right after set_framesize() on this board).
 *   2. When a bounding box clears DETECTION_THRESHOLD, POST that same frame
 *      (multipart/form-data) to the RPi5 detection server (see API contract in
 *      README / claude_code_prompt.md 4.1).
 *   3. POST failures are retried with exponential backoff. Status is reported on the
 *      on-board LED and over Serial.
 *
 * All secrets/tunables live in include/config.h (gitignored) — copy from config.h.example.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "esp_camera.h"

#include <Person_detection_FOMO_inferencing.h>
#include "edge-impulse-sdk/dsp/image/image.hpp"

#include "config.h"

// run_classifier() needs a bigger stack than the default loop task gets.
SET_LOOP_TASK_STACK_SIZE(20 * 1024);

// ================= [1. Camera pin map — XIAO ESP32S3 Sense] =================
#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     10
#define SIOD_GPIO_NUM     40
#define SIOC_GPIO_NUM     39

#define Y9_GPIO_NUM       48
#define Y8_GPIO_NUM       11
#define Y7_GPIO_NUM       12
#define Y6_GPIO_NUM       14
#define Y5_GPIO_NUM       16
#define Y4_GPIO_NUM       18
#define Y3_GPIO_NUM       17
#define Y2_GPIO_NUM       15
#define VSYNC_GPIO_NUM    38
#define HREF_GPIO_NUM     47
#define PCLK_GPIO_NUM     13

// Single capture resolution for both inference and violation uploads — see the
// comment on CAPTURE_FRAMESIZE in config.h for why there's no resolution switch.
#define PREVIEW_BYTES_PER_PIXEL    3                // RGB888 scratch buffer
#define CAPTURED_JPEG_BUF_SIZE     (200 * 1024)      // generous headroom for a VGA JPEG at quality 12

static camera_config_t camera_config = {
    .pin_pwdn = PWDN_GPIO_NUM,
    .pin_reset = RESET_GPIO_NUM,
    .pin_xclk = XCLK_GPIO_NUM,
    .pin_sscb_sda = SIOD_GPIO_NUM,
    .pin_sscb_scl = SIOC_GPIO_NUM,

    .pin_d7 = Y9_GPIO_NUM,
    .pin_d6 = Y8_GPIO_NUM,
    .pin_d5 = Y7_GPIO_NUM,
    .pin_d4 = Y6_GPIO_NUM,
    .pin_d3 = Y5_GPIO_NUM,
    .pin_d2 = Y4_GPIO_NUM,
    .pin_d1 = Y3_GPIO_NUM,
    .pin_d0 = Y2_GPIO_NUM,
    .pin_vsync = VSYNC_GPIO_NUM,
    .pin_href = HREF_GPIO_NUM,
    .pin_pclk = PCLK_GPIO_NUM,

    .xclk_freq_hz = 20000000,
    .ledc_timer = LEDC_TIMER_0,
    .ledc_channel = LEDC_CHANNEL_0,

    .pixel_format = PIXFORMAT_JPEG,
    .frame_size = CAPTURE_FRAMESIZE,

    .jpeg_quality = JPEG_QUALITY,
    .fb_count = 1,
    .fb_location = CAMERA_FB_IN_PSRAM,
    .grab_mode = CAMERA_GRAB_WHEN_EMPTY,
};

static bool     camera_ready  = false;
static uint8_t *preview_rgb_buf = nullptr;   // scratch buffer for JPEG->RGB888->resize (inference only)
static uint8_t *captured_jpeg_buf = nullptr; // copy of this cycle's raw JPEG, reused for upload if a person is found
static size_t   captured_jpeg_len = 0;

// ================= [2. Status LED] =================
static void ledInit() {
    if (STATUS_LED_PIN < 0) return;
    pinMode(STATUS_LED_PIN, OUTPUT);
    digitalWrite(STATUS_LED_PIN, STATUS_LED_ACTIVE_LOW ? HIGH : LOW); // off
}

static void ledSet(bool on) {
    if (STATUS_LED_PIN < 0) return;
    digitalWrite(STATUS_LED_PIN, on == STATUS_LED_ACTIVE_LOW ? LOW : HIGH);
}

static void ledBlink(int times, int on_ms, int off_ms) {
    for (int i = 0; i < times; i++) {
        ledSet(true);
        delay(on_ms);
        ledSet(false);
        if (i != times - 1) delay(off_ms);
    }
}

// ================= [3. Wi-Fi] =================
static void wifiConnect() {
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        delay(400);
        Serial.print(".");
        if (millis() - start > 20000) {
            Serial.println("\n[WiFi] Still not connected, retrying begin()...");
            WiFi.disconnect(true);
            delay(500);
            WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
            start = millis();
        }
    }
    Serial.printf("\n[WiFi] Connected. IP=%s\n", WiFi.localIP().toString().c_str());
}

// ================= [4. Camera capture + FOMO inference] =================
bool ei_camera_init(void) {
    esp_err_t err = esp_camera_init(&camera_config);
    if (err != ESP_OK) {
        Serial.printf("[Camera] Init failed: 0x%x\n", err);
        return false;
    }

    sensor_t *s = esp_camera_sensor_get();
    if (s != NULL) {
        s->set_vflip(s, 1);
        s->set_hmirror(s, 0);
    }
    return true;
}

// Captures one JPEG frame, keeps a raw copy of it (captured_jpeg_buf/len — reused
// as the violation upload image if this cycle detects a person, so no second
// capture or resolution switch is ever needed), then decodes+resizes it into
// preview_rgb_buf for the classifier.
bool ei_camera_capture_for_inference() {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) return false;

    if (fb->len <= CAPTURED_JPEG_BUF_SIZE) {
        memcpy(captured_jpeg_buf, fb->buf, fb->len);
        captured_jpeg_len = fb->len;
    } else {
        Serial.printf("[Camera] Captured JPEG (%u bytes) exceeds buffer, can't keep it for upload\n", (unsigned)fb->len);
        captured_jpeg_len = 0;
    }

    bool converted = fmt2rgb888(fb->buf, fb->len, PIXFORMAT_JPEG, preview_rgb_buf);
    esp_camera_fb_return(fb);
    if (!converted) {
        Serial.println("[Camera] fmt2rgb888 conversion failed");
        return false;
    }

    if (CAPTURE_COLS != EI_CLASSIFIER_INPUT_WIDTH || CAPTURE_ROWS != EI_CLASSIFIER_INPUT_HEIGHT) {
        ei::image::processing::crop_and_interpolate_rgb888(
            preview_rgb_buf, CAPTURE_COLS, CAPTURE_ROWS,
            preview_rgb_buf, EI_CLASSIFIER_INPUT_WIDTH, EI_CLASSIFIER_INPUT_HEIGHT);
    }
    return true;
}

static int ei_camera_get_data(size_t offset, size_t length, float *out_ptr) {
    size_t pixel_ix = offset * 3;
    size_t pixels_left = length;
    size_t out_ptr_ix = 0;

    while (pixels_left != 0) {
        out_ptr[out_ptr_ix] = (float)((preview_rgb_buf[pixel_ix] << 16) +
                                       (preview_rgb_buf[pixel_ix + 1] << 8) +
                                       preview_rgb_buf[pixel_ix + 2]);
        out_ptr_ix++;
        pixel_ix += 3;
        pixels_left--;
    }
    return 0;
}

// ================= [5. HTTP upload: multipart/form-data to RPi5] =================
// POST /api/v1/detect — fields: image (jpeg), device_id, timestamp (ISO8601), confidence
static bool uploadDetection(const uint8_t *jpeg_buf, size_t jpeg_len, float confidence,
                             const String &timestamp, String &out_response) {
    static const char *BOUNDARY = "----esp32Boundary7MA4YWxkTrZu0gW";

    String head;
    head += "--"; head += BOUNDARY; head += "\r\n";
    head += "Content-Disposition: form-data; name=\"device_id\"\r\n\r\n";
    head += DEVICE_ID; head += "\r\n";

    head += "--"; head += BOUNDARY; head += "\r\n";
    head += "Content-Disposition: form-data; name=\"timestamp\"\r\n\r\n";
    head += timestamp; head += "\r\n";

    head += "--"; head += BOUNDARY; head += "\r\n";
    head += "Content-Disposition: form-data; name=\"confidence\"\r\n\r\n";
    head += String(confidence, 4); head += "\r\n";

    head += "--"; head += BOUNDARY; head += "\r\n";
    head += "Content-Disposition: form-data; name=\"image\"; filename=\"capture.jpg\"\r\n";
    head += "Content-Type: image/jpeg\r\n\r\n";

    String tail = "\r\n--"; tail += BOUNDARY; tail += "--\r\n";

    size_t total_len = head.length() + jpeg_len + tail.length();
    uint8_t *body = (uint8_t *)ps_malloc(total_len);
    if (!body) {
        Serial.println("[HTTP] Failed to allocate multipart body buffer");
        return false;
    }

    size_t pos = 0;
    memcpy(body + pos, head.c_str(), head.length()); pos += head.length();
    memcpy(body + pos, jpeg_buf, jpeg_len);          pos += jpeg_len;
    memcpy(body + pos, tail.c_str(), tail.length()); pos += tail.length();

    HTTPClient http;
    String url = String(SERVER_BASE_URL) + SERVER_DETECT_PATH;
    http.begin(url);
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.addHeader("Content-Type", String("multipart/form-data; boundary=") + BOUNDARY);

    int status = http.POST(body, total_len);
    bool ok = (status >= 200 && status < 300);
    if (ok) {
        out_response = http.getString();
    } else {
        Serial.printf("[HTTP] POST failed, status=%d\n", status);
    }

    http.end();
    free(body);
    return ok;
}

static bool uploadDetectionWithRetry(const uint8_t *jpeg_buf, size_t jpeg_len, float confidence,
                                      const String &timestamp) {
    uint32_t backoff = HTTP_BACKOFF_BASE_MS;
    for (int attempt = 1; attempt <= HTTP_MAX_RETRIES; attempt++) {
        String response;
        Serial.printf("[HTTP] Upload attempt %d/%d (%u bytes)\n", attempt, HTTP_MAX_RETRIES, (unsigned)jpeg_len);

        if (uploadDetection(jpeg_buf, jpeg_len, confidence, timestamp, response)) {
            String requestId = "?";
            JsonDocument doc;
            if (!deserializeJson(doc, response)) {
                requestId = doc["request_id"] | "?";
            }
            Serial.printf("[HTTP] Upload OK, request_id=%s\n", requestId.c_str());
            return true;
        }

        if (attempt < HTTP_MAX_RETRIES) {
            Serial.printf("[HTTP] Retrying in %u ms...\n", backoff);
            delay(backoff);
            backoff *= 2;
        }
    }
    Serial.println("[HTTP] All upload attempts failed, giving up on this detection");
    return false;
}

// ISO8601 UTC timestamp. Requires SNTP time sync in setup(); falls back to uptime-based
// placeholder if the clock hasn't synced yet (still monotonic, clearly not wall-clock).
static String isoTimestampNow() {
    time_t now;
    time(&now);
    if (now < 1700000000) { // clock not synced yet (before ~2023)
        char buf[32];
        snprintf(buf, sizeof(buf), "1970-01-01T00:00:%02luZ", (unsigned long)(millis() / 1000) % 60);
        return String(buf);
    }
    struct tm timeinfo;
    gmtime_r(&now, &timeinfo);
    char buf[32];
    strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &timeinfo);
    return String(buf);
}

// ================= [6. setup / loop] =================
void setup() {
    Serial.begin(115200);
    delay(1500);
    Serial.println("\n=== ESP32-S3 person-detection node starting ===");

    ledInit();

    size_t rgb_buf_size = CAPTURE_COLS * CAPTURE_ROWS * PREVIEW_BYTES_PER_PIXEL;
    preview_rgb_buf = (uint8_t *)ps_malloc(rgb_buf_size);
    if (!preview_rgb_buf) preview_rgb_buf = (uint8_t *)malloc(rgb_buf_size);
    if (!preview_rgb_buf) {
        Serial.println("[FATAL] Could not allocate preview RGB buffer");
        while (true) { ledBlink(1, 100, 100); }
    }

    captured_jpeg_buf = (uint8_t *)ps_malloc(CAPTURED_JPEG_BUF_SIZE);
    if (!captured_jpeg_buf) {
        Serial.println("[FATAL] Could not allocate captured-JPEG buffer");
        while (true) { ledBlink(1, 100, 100); }
    }

    camera_ready = ei_camera_init();
    if (!camera_ready) {
        Serial.println("[FATAL] Camera init failed");
        while (true) { ledBlink(2, 100, 300); }
    }

    wifiConnect();
    configTime(0, 0, "pool.ntp.org", "time.nist.gov"); // UTC, for ISO8601 timestamps

    Serial.println("Camera + Wi-Fi ready. Starting detection loop...");
    ledBlink(3, 80, 80);
}

void loop() {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[WiFi] Lost connection, reconnecting...");
        ledBlink(1, 50, 950); // slow single blink = degraded/reconnecting
        WiFi.reconnect();
        delay(1000);
        return;
    }

    static uint32_t last_infer_ms = 0;
    static uint32_t last_capture_ms = 0;
    if (millis() - last_infer_ms < CAPTURE_INTERVAL_MS) {
        delay(10);
        return;
    }
    last_infer_ms = millis();

    if (!ei_camera_capture_for_inference()) {
        Serial.println("[ERR] Preview capture failed");
        return;
    }

    ei::signal_t signal;
    signal.total_length = EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
    signal.get_data = &ei_camera_get_data;

    ei_impulse_result_t result = {0};
    EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false /* debug */);
    if (err != EI_IMPULSE_OK) {
        Serial.printf("[ERR] Classifier returned %d\n", err);
        return;
    }

    bool  person_detected = false;
    float best_confidence  = 0.0f;

#if EI_CLASSIFIER_OBJECT_DETECTION == 1
    // Debug view of EVERY box the SDK returned, before our own DETECTION_THRESHOLD
    // filter — use this to tune sensitivity. NOTE: the FOMO model itself was
    // exported with its own internal detection threshold (EI_CLASSIFIER_OBJECT_
    // DETECTION_THRESHOLD, baked into lib/.../model_metadata.h at export time —
    // currently 0.5 for this model). The SDK only returns boxes that already
    // cleared THAT threshold, so result.bounding_boxes never contains anything
    // below it — lowering DETECTION_THRESHOLD below 0.5 here will have no effect.
    // If nothing shows up at all even with a person clearly in frame, the model's
    // own 0.5 floor is the actual blocker and it needs re-exporting from Edge
    // Impulse Studio with a lower object detection threshold, not a config.h change.
    if (result.bounding_boxes_count == 0) {
        Serial.println("[Debug] 0 boxes from SDK this cycle (nothing cleared the model's own >=0.5 floor)");
    }
    for (uint32_t i = 0; i < result.bounding_boxes_count; i++) {
        ei_impulse_result_bounding_box_t bb = result.bounding_boxes[i];
        Serial.printf("[Debug] box: label=%s value=%.3f [x:%u,y:%u,w:%u,h:%u] (our threshold=%.2f)\n",
                      bb.label, bb.value, bb.x, bb.y, bb.width, bb.height, DETECTION_THRESHOLD);
        if (bb.value >= DETECTION_THRESHOLD && bb.value > best_confidence) {
            person_detected = true;
            best_confidence = bb.value;
        }
    }
#endif

    if (!person_detected) return;

    Serial.printf("[Detect] Person detected, confidence=%.2f\n", best_confidence);
    ledSet(true); // solid on = person currently in frame

    bool cooldown_active = (millis() - last_capture_ms) < CAPTURE_COOLDOWN_MS;
    if (cooldown_active) {
        Serial.println("[Detect] Within cooldown window, skipping upload");
        ledSet(false);
        return;
    }

    if (captured_jpeg_len == 0) {
        // This cycle's frame was too large for captured_jpeg_buf (see the
        // [Camera] warning above) — nothing to upload. Not a cooldown-worthy
        // event; try again next cycle.
        Serial.println("[ERR] No captured JPEG available to upload this cycle");
        ledBlink(4, 60, 60); // fast blink = capture error
        ledSet(false);
        return;
    }
    last_capture_ms = millis();

    String ts = isoTimestampNow();
    bool ok = uploadDetectionWithRetry(captured_jpeg_buf, captured_jpeg_len, best_confidence, ts);

    if (ok) {
        ledBlink(2, 150, 150); // double blink = upload success
    } else {
        ledBlink(6, 60, 60);   // rapid blink = upload failure after retries
    }
    ledSet(false);
}
