// ESP32-CAM 얼굴 인식 -> MQTT Publish 예시 (Windows용 Mosquitto로 전송)
// 기존 얼굴 인식 로직(state 계산)은 그대로 두고, WiFi + PubSubClient 관련 부분만 추가/변경했습니다.
// 아두이노 라이브러리 매니저에서 "PubSubClient"(knolleary) 설치 필요.

#include <Arduino.h>
#include "esp_camera.h"
#include "img_converters.h"
#include "Face_detection_-_FOMO_-_Embedded_Online_Conference_inferencing.h"
#include <WiFi.h>          // [ADD]
#include <PubSubClient.h>  // [ADD]

#define TH 0.15
#define MISS_MAX 3

#define PWDN -1
#define RESET -1
#define XCLK 10
#define SIOD 40
#define SIOC 39
#define Y9 48
#define Y8 11
#define Y7 12
#define Y6 14
#define Y5 16
#define Y4 18
#define Y3 17
#define Y2 15
#define VSYNC 38
#define HREF 47
#define PCLK 13

// [ADD] Wi-Fi 설정 — 본인 환경에 맞게 값만 바꾸면 됨
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";

// [ADD] MQTT 설정 — PC에서 실행 중인 Mosquitto for Windows
const char* MQTT_SERVER = "192.168.45.226";
const int   MQTT_PORT   = 1883;
const char* MQTT_TOPIC  = "zero_touch/face";

WiFiClient espClient;         // [ADD]
PubSubClient mqtt(espClient); // [ADD]

uint8_t *img;
int state=0, miss=0;

int get_data(size_t off,size_t len,float *out){
  size_t p=off*3;
  for(size_t i=0;i<len;i++){
    out[i]=((uint32_t)img[p]<<16)|((uint32_t)img[p+1]<<8)|img[p+2];
    p+=3;
  }
  return 0;
}

void resizeImg(uint8_t *s,int sw,int sh,uint8_t *d,int dw,int dh){
  for(int y=0;y<dh;y++) for(int x=0;x<dw;x++){
    int si=((y*sh/dh)*sw+(x*sw/dw))*3;
    int di=(y*dw+x)*3;
    d[di]=s[si]; d[di+1]=s[si+1]; d[di+2]=s[si+2];
  }
}

// [ADD] MQTT 브로커에 연결(끊겼으면 재연결)
void ensureMqttConnected(){
  while(!mqtt.connected()){
    mqtt.connect("esp32-cam-face");
    if(!mqtt.connected()) delay(1000);
  }
}

// [ADD] 얼굴 인식 상태를 MQTT로 publish
void publishFace(int face){
  if(WiFi.status()!=WL_CONNECTED) return;
  ensureMqttConnected();
  String payload = String("{\"face\":") + face + "}";
  mqtt.publish(MQTT_TOPIC, payload.c_str());
}

void setup(){
  Serial.begin(115200);

  // [ADD] Wi-Fi 연결
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi connecting");
  while(WiFi.status()!=WL_CONNECTED){
    delay(300);
    Serial.print(".");
  }
  Serial.println(" connected: " + WiFi.localIP().toString());

  // [ADD] MQTT 브로커 지정
  mqtt.setServer(MQTT_SERVER, MQTT_PORT);

  camera_config_t c={};
  c.ledc_channel=LEDC_CHANNEL_0;
  c.ledc_timer=LEDC_TIMER_0;
  c.pin_d0=Y2; c.pin_d1=Y3; c.pin_d2=Y4; c.pin_d3=Y5;
  c.pin_d4=Y6; c.pin_d5=Y7; c.pin_d6=Y8; c.pin_d7=Y9;
  c.pin_xclk=XCLK; c.pin_pclk=PCLK;
  c.pin_vsync=VSYNC; c.pin_href=HREF;
  c.pin_sccb_sda=SIOD; c.pin_sccb_scl=SIOC;
  c.pin_pwdn=PWDN; c.pin_reset=RESET;
  c.xclk_freq_hz=20000000;
  c.pixel_format=PIXFORMAT_JPEG;
  c.frame_size=FRAMESIZE_QVGA;
  c.jpeg_quality=12;
  c.fb_count=1;
  c.fb_location=CAMERA_FB_IN_PSRAM;

  if(esp_camera_init(&c)!=ESP_OK) while(1);

  img=(uint8_t*)ps_malloc(
    EI_CLASSIFIER_INPUT_WIDTH*
    EI_CLASSIFIER_INPUT_HEIGHT*3
  );

  Serial.println("READY");
}

void loop(){
  mqtt.loop(); // [ADD] MQTT 클라이언트 유지

  camera_fb_t *fb=esp_camera_fb_get();
  if(!fb) return;

  int w=fb->width,h=fb->height;
  uint8_t *rgb=(uint8_t*)ps_malloc(w*h*3);

  if(!rgb){
    esp_camera_fb_return(fb);
    return;
  }

  bool ok=fmt2rgb888(fb->buf,fb->len,fb->format,rgb);
  esp_camera_fb_return(fb);

  if(!ok){
    free(rgb);
    return;
  }

  resizeImg(
    rgb,w,h,img,
    EI_CLASSIFIER_INPUT_WIDTH,
    EI_CLASSIFIER_INPUT_HEIGHT
  );
  free(rgb);

  signal_t signal;
  signal.total_length=
    EI_CLASSIFIER_INPUT_WIDTH*
    EI_CLASSIFIER_INPUT_HEIGHT;
  signal.get_data=get_data;

  ei_impulse_result_t result={0};

  bool face=false;

  if(run_classifier(&signal,&result,false)==EI_IMPULSE_OK){
#if EI_CLASSIFIER_OBJECT_DETECTION == 1
    for(size_t i=0;i<EI_CLASSIFIER_OBJECT_DETECTION_COUNT;i++){
      if(result.bounding_boxes[i].value>=TH){
        face=true;
        break;
      }
    }
#endif
  }

  if(face){
    state=1;
    miss=0;
  }else{
    miss++;
    if(miss>=MISS_MAX) state=0;
  }

  Serial.println(state);
  publishFace(state); // [ADD] MQTT로 상태 발행 (zero_touch/face)

  delay(300);
}
