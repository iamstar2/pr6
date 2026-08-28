/* Edge Impulse Face Detection + MQTT for XIAO ESP32S3 Sense (FOMO)
 *
 * 추론 파이프라인은 손대지 않았다 (JPEG QVGA -> RGB888 -> 96x96 리사이즈).
 * 얼굴이 잡히면 "감지되었다"는 판단 결과 JSON 만 MQTT 로 보낸다. 사진은 보내지 않는다.
 *
 * 페이로드 (web/server.js 가 그대로 파싱하는 형식):
 *   {"face":1,"count":1,"score":0.87,"up":123}
 *   - 상태가 바뀌면 즉시, 안 바뀌면 HEARTBEAT_MS 주기로 발행 (retain)
 *   - 보드가 죽으면 브로커가 LWT {"face":0,...,"online":0} 을 대신 발행
 */

#include <Face_detection_-_FOMO_-_Embedded_Online_Conference_inferencing.h>
#include "edge-impulse-sdk/dsp/image/image.hpp"
#include "esp_camera.h"
#include <WiFi.h>
#include <PubSubClient.h>

// run_classifier 가 loop task 스택을 많이 쓴다
SET_LOOP_TASK_STACK_SIZE(20 * 1024);

// ================= [0. 네트워크 / 판정 설정] =================
// NOTE: 원본 코드에 실제 Wi-Fi 비밀번호/MQTT IP가 하드코딩되어 있어 GitHub 공유 전에 지웠습니다.
// 이 파일은 참고용 레퍼런스일 뿐 빌드 대상이 아닙니다 (실제 빌드는 esp32/src/main.cpp +
// esp32/include/config.h 사용).
const char* ssid        = "your-wifi-ssid";
const char* password    = "your-wifi-password";
const char* mqtt_server = "192.168.0.0"; // placeholder — 원래 값은 로컬 MQTT 브로커 IP
const int   mqtt_port   = 1883;
const char* mqtt_topic  = "esp32/face";

#define CONFIDENCE_THRESHOLD   0.15f   // 이 값 이상만 얼굴로 인정 (기존 동작 유지)
#define HEARTBEAT_MS           1000    // 상태가 그대로여도 이 주기로는 발행
#define INFER_INTERVAL_MS      100     // 추론 간격

WiFiClient   espClient;
PubSubClient client(espClient);

static bool     published_face  = false;
static bool     has_published   = false;
static uint32_t last_publish_ms = 0;

// ================= [1. 카메라 핀맵] =================
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

#define EI_CAMERA_RAW_FRAME_BUFFER_COLS           320
#define EI_CAMERA_RAW_FRAME_BUFFER_ROWS           240
#define EI_CAMERA_FRAME_BYTE_SIZE                 3

static bool debug_nn = false;
static bool is_initialised = false;
static uint8_t *snapshot_buf = nullptr;

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
    .frame_size = FRAMESIZE_QVGA, // 320x240

    .jpeg_quality = 12,
    .fb_count = 1,
    .fb_location = CAMERA_FB_IN_PSRAM,
    .grab_mode = CAMERA_GRAB_WHEN_EMPTY,
};

bool ei_camera_init(void);
bool ei_camera_capture(uint32_t img_width, uint32_t img_height, uint8_t *out_buf);
static int ei_camera_get_data(size_t offset, size_t length, float *out_ptr);

// ================= [2. MQTT] =================
void publishFaceState(bool face, uint32_t count, float score) {
    char payload[96];
    int n = snprintf(payload, sizeof(payload),
                     "{\"face\":%d,\"count\":%lu,\"score\":%.2f,\"up\":%lu}",
                     face ? 1 : 0, (unsigned long)count, score,
                     (unsigned long)(millis() / 1000));

    if (client.publish(mqtt_topic, (const uint8_t*)payload, (unsigned int)n, true)) {
        Serial.printf(">> Published: %s\n", payload);
    } else {
        Serial.println(">> Publish FAILED");
    }

    published_face  = face;
    has_published   = true;
    last_publish_ms = millis();
}

bool connectMQTT(int max_tries) {
    for (int i = 0; i < max_tries; i++) {
        if (client.connected()) return true;
        Serial.print("Connecting to MQTT Broker...");
        String clientId = "XIAO_ESP32S3_" + String((uint32_t)ESP.getEfuseMac(), HEX);
        const char* lwt = "{\"face\":0,\"count\":0,\"score\":0.00,\"online\":0}";

        if (client.connect(clientId.c_str(), mqtt_topic, 1, true, lwt)) {
            Serial.println(" Connected!");
            has_published = false;   // 재연결 직후엔 현재 상태를 한 번 다시 보낸다
            return true;
        }
        Serial.printf(" Failed, rc=%d. Retry in 2s...\n", client.state());
        delay(2000);
    }
    return false;
}

// ================= [3. setup] =================
void setup() {
    Serial.begin(115200);
    delay(2000);   // 시리얼 모니터 없이도 부팅되도록 while(!Serial) 대신 고정 대기
    Serial.println("XIAO ESP32S3 FOMO Face Detection + MQTT Starting...");

    if (!ei_camera_init()) {
        Serial.println("ERR: Camera Init Failed!");
        while (1) delay(1000);
    }

    // 전역 안전 버퍼 할당 (PSRAM 우선 - WiFi 스택이 내부 힙을 많이 쓴다)
    size_t buf_size = EI_CAMERA_RAW_FRAME_BUFFER_COLS * EI_CAMERA_RAW_FRAME_BUFFER_ROWS * EI_CAMERA_FRAME_BYTE_SIZE;
    snapshot_buf = (uint8_t*)ps_malloc(buf_size);
    if (!snapshot_buf) snapshot_buf = (uint8_t*)malloc(buf_size);
    if (!snapshot_buf) {
        Serial.println("ERR: Failed to allocate snapshot buffer!");
        while (1) delay(1000);
    }

    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    WiFi.begin(ssid, password);
    while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
    Serial.println("\nWiFi Connected! IP: " + WiFi.localIP().toString());

    client.setServer(mqtt_server, mqtt_port);
    client.setKeepAlive(15);
    client.setSocketTimeout(5);
    connectMQTT(5);

    Serial.println("Camera ready. Starting inference...");
    delay(2000);
}

// ================= [4. loop] =================
void loop() {
    if (!snapshot_buf) return;

    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("WiFi lost, reconnecting...");
        WiFi.reconnect();
        delay(1000);
        return;
    }
    if (!client.connected()) {
        if (!connectMQTT(2)) { delay(500); return; }
    }
    client.loop();

    static uint32_t last_infer = 0;
    if (millis() - last_infer < INFER_INTERVAL_MS) { delay(5); return; }
    last_infer = millis();

    if (!ei_camera_capture(EI_CLASSIFIER_INPUT_WIDTH, EI_CLASSIFIER_INPUT_HEIGHT, snapshot_buf)) {
        Serial.println("ERR: Capture failed");
        delay(100);
        return;
    }

    ei::signal_t signal;
    signal.total_length = EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
    signal.get_data = &ei_camera_get_data;

    ei_impulse_result_t result = { 0 };
    EI_IMPULSE_ERROR err = run_classifier(&signal, &result, debug_nn);
    if (err != EI_IMPULSE_OK) {
        Serial.printf("ERR: Classifier returned %d\n", err);
        return;
    }

    Serial.printf("Predictions (DSP: %d ms, Infer: %d ms)\n",
                  result.timing.dsp, result.timing.classification);

    bool     face_detected = false;
    uint32_t face_count    = 0;
    float    best_score    = 0.0f;

#if EI_CLASSIFIER_OBJECT_DETECTION == 1
    for (uint32_t i = 0; i < result.bounding_boxes_count; i++) {
        ei_impulse_result_bounding_box_t bb = result.bounding_boxes[i];
        if (bb.value >= CONFIDENCE_THRESHOLD) {
            face_detected = true;
            face_count++;
            if (bb.value > best_score) best_score = bb.value;
            Serial.printf("  >> DETECTED: %s (%.1f%%) [x:%u, y:%u, w:%u, h:%u]\n",
                          bb.label, bb.value * 100.0f, bb.x, bb.y, bb.width, bb.height);
        }
    }
    if (!face_detected) {
        Serial.println("  No face detected");
    }
#endif

    // 상태가 바뀌면 즉시, 아니면 하트비트 주기로 발행 (이미지는 절대 보내지 않는다)
    uint32_t now_ms  = millis();
    bool     changed = (!has_published || face_detected != published_face);
    if (changed || (now_ms - last_publish_ms) >= HEARTBEAT_MS) {
        publishFaceState(face_detected, face_count, best_score);
    }

    delay(10);
}

// ================= [5. 카메라] =================
bool ei_camera_init(void) {
    if (is_initialised) return true;

    esp_err_t err = esp_camera_init(&camera_config);
    if (err != ESP_OK) {
        Serial.printf("Camera init failed: 0x%x\n", err);
        return false;
    }

    sensor_t * s = esp_camera_sensor_get();
    if (s != NULL) {
        // XIAO ESP32S3 기본 장착 방향 보정
        s->set_vflip(s, 1);
        s->set_hmirror(s, 0);
        s->set_brightness(s, 0);  // 과노출(빛 번짐) 방지
        s->set_contrast(s, 2);    // 이목구비 윤곽 강조 (0 -> 2)
    }

    is_initialised = true;
    return true;
}

bool ei_camera_capture(uint32_t img_width, uint32_t img_height, uint8_t *out_buf) {
    if (!is_initialised) return false;

    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) return false;

    // JPEG -> RGB888 디코딩
    bool converted = fmt2rgb888(fb->buf, fb->len, PIXFORMAT_JPEG, out_buf);
    esp_camera_fb_return(fb);

    if (!converted) {
        Serial.println("ERR: fmt2rgb888 conversion failed");
        return false;
    }

    // 320x240 RGB888 -> 모델 입력 크기(96x96)로 리사이징
    if ((img_width != EI_CAMERA_RAW_FRAME_BUFFER_COLS) || (img_height != EI_CAMERA_RAW_FRAME_BUFFER_ROWS)) {
        ei::image::processing::crop_and_interpolate_rgb888(
            out_buf,
            EI_CAMERA_RAW_FRAME_BUFFER_COLS,
            EI_CAMERA_RAW_FRAME_BUFFER_ROWS,
            out_buf,
            img_width,
            img_height);
    }

    return true;
}

static int ei_camera_get_data(size_t offset, size_t length, float *out_ptr) {
    size_t pixel_ix = offset * 3;
    size_t pixels_left = length;
    size_t out_ptr_ix = 0;

    while (pixels_left != 0) {
        // 표준 RGB 순서로 패킹 (BGR 스왑 버그 수정)
        out_ptr[out_ptr_ix] = (float)((snapshot_buf[pixel_ix] << 16) + (snapshot_buf[pixel_ix + 1] << 8) + snapshot_buf[pixel_ix + 2]);

        out_ptr_ix++;
        pixel_ix += 3;
        pixels_left--;
    }
    return 0;
}
