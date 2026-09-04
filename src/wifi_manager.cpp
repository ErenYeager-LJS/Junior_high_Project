#include "wifi_manager.h"

#include <ESP8266WiFi.h>

#include "wifi_secrets.h"

namespace {
// 尝试一个密码时最多等待 8 秒。
constexpr uint32_t PASSWORD_TIMEOUT_MS = 8000;
// 断线后每 10 秒重新尝试一次，避免持续占用主循环。
constexpr uint32_t RETRY_INTERVAL_MS = 10000;
// 记录上一次重连尝试的系统毫秒数。
uint32_t lastAttempt = 0;
}

// 依次尝试配置文件中的密码，并在串口打印连接结果。
bool wifiConnect() {
  WiFi.mode(WIFI_STA);
  // password 指向当前正在尝试的密码文本。
  for (const char* password : WIFI_PASSWORDS) {
    WiFi.begin(WIFI_SSID, password);
    // startedAt 用来计算本次连接已经等待了多久。
    const uint32_t startedAt = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - startedAt < PASSWORD_TIMEOUT_MS) {
      delay(100);
    }
    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("WiFi connected, IP: %s\n", WiFi.localIP().toString().c_str());
      return true;
    }
    WiFi.disconnect();
    delay(100);
  }
  Serial.println("WiFi connection failed.");
  return false;
}

// 已连接时不做事；断线且到达重试时间时调用 wifiConnect。
void wifiMaintain(uint32_t now) {
  if (WiFi.status() == WL_CONNECTED || now - lastAttempt < RETRY_INTERVAL_MS) return;
  lastAttempt = now;
  wifiConnect();
}
