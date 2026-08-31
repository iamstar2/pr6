#pragma once
// Compile-time log leveling. LOG_LEVEL (config.h) is checked at compile time via
// #if, so anything below it is stripped from the binary entirely — not just
// silenced at runtime — which is what actually lets you drop per-detection debug
// spam (LOGD) from a production build instead of just filtering it on a PC.
#define LOG_LEVEL_ERROR 0
#define LOG_LEVEL_INFO  1
#define LOG_LEVEL_DEBUG 2

#if LOG_LEVEL >= LOG_LEVEL_ERROR
#define LOGE(fmt, ...) Serial.printf("[ERROR] " fmt "\n", ##__VA_ARGS__)
#else
#define LOGE(fmt, ...)
#endif

#if LOG_LEVEL >= LOG_LEVEL_INFO
#define LOGI(fmt, ...) Serial.printf("[INFO] " fmt "\n", ##__VA_ARGS__)
#else
#define LOGI(fmt, ...)
#endif

#if LOG_LEVEL >= LOG_LEVEL_DEBUG
#define LOGD(fmt, ...) Serial.printf("[DEBUG] " fmt "\n", ##__VA_ARGS__)
#else
#define LOGD(fmt, ...)
#endif
