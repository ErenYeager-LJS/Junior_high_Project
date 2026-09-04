#include <Arduino.h>
#include <ESP8266HTTPClient.h>
#include <ESP8266WiFi.h>
#include <WiFiClient.h>

#include "wifi_secrets.h"
#include "command_client.h"
#include "led_control.h"

// 串口 0 的通信速度，用于输出调试信息。
constexpr uint32_t UART0_BAUD_RATE = 921600;
// 两次 A0 采样之间的间隔：4 ms 对应目标采样率 250 Hz。
constexpr uint32_t ADC_SAMPLE_INTERVAL_MS = 4;
// 每隔 500 ms 向 Flask 批量上报一次状态和采样值。
constexpr uint32_t REPORT_INTERVAL_MS = 500;
// Wi-Fi 断开后，每隔 10 秒尝试重新连接一次。
constexpr uint32_t WIFI_RETRY_INTERVAL_MS = 10000;
// 尝试一个 Wi-Fi 密码时，最多等待 8 秒。
constexpr uint32_t WIFI_PASSWORD_TIMEOUT_MS = 8000;
// 环形缓冲区最多保存 128 个尚未成功上报的 ADC 值。
constexpr size_t ADC_BUFFER_SIZE = 128;
// ESP8266 将设备状态发送到这个 Flask 接口。
constexpr char STATUS_URL[] = "http://192.168.124.3:5000/api/status";

// 环形缓冲区：临时保存等待上报的 A0 原始值。
uint16_t adcSamples[ADC_BUFFER_SIZE] = {};
// 下一次 ADC 采样要写入缓冲区的位置。
size_t adcWriteIndex = 0;
// 缓冲区里目前有多少个有效采样值。
size_t adcSampleCount = 0;
// 上一次执行 A0 采样时的系统毫秒数。
uint32_t lastAdcSample = 0;
// 上一次向 Flask 上报状态时的系统毫秒数。
uint32_t lastReport = 0;
// 上一次尝试重连 Wi-Fi 时的系统毫秒数。
uint32_t lastWiFiAttempt = 0;

// 依次尝试配置文件中的 Wi-Fi 密码，连接成功返回 true。
bool connectWiFi() {
  WiFi.mode(WIFI_STA);

  // password 是当前正在尝试的 Wi-Fi 密码。
  for (const char* password : WIFI_PASSWORDS) {
    WiFi.begin(WIFI_SSID, password);
    // startedAt 用来计算本次连接已经等待了多久。
    const uint32_t startedAt = millis();

    while (WiFi.status() != WL_CONNECTED &&
           millis() - startedAt < WIFI_PASSWORD_TIMEOUT_MS) {
      delay(100);
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("WiFi connected: %s, IP: %s\n", WIFI_SSID,
                    WiFi.localIP().toString().c_str());
      return true;
    }

    WiFi.disconnect();
    delay(100);
  }

  Serial.println("WiFi connection failed; retrying later.");
  return false;
}

// 到达采样时刻时读取一次 A0，并把结果写入环形缓冲区。
// now 是当前系统运行时间，单位为毫秒。
void sampleAdc(uint32_t now) {
  if (now - lastAdcSample < ADC_SAMPLE_INTERVAL_MS) {
    return;
  }

  lastAdcSample = now;
  adcSamples[adcWriteIndex] = analogRead(A0);
  adcWriteIndex = (adcWriteIndex + 1) % ADC_BUFFER_SIZE;
  if (adcSampleCount < ADC_BUFFER_SIZE) {
    ++adcSampleCount;
  }
}

// 把 LED 状态、网络信息和暂存的 ADC 数据批量发送给 Flask。
void reportStatus() {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  // client 提供 TCP 连接，http 在其上封装 HTTP 请求。
  WiFiClient client;
  HTTPClient http;
  http.setTimeout(750);

  if (!http.begin(client, STATUS_URL)) {
    return;
  }

  // payload 是本次 POST 请求发送的 JSON 文本。
  String payload;
  payload.reserve(1024);
  payload = String("{\"led\":") + (ledIsOn() ? "true" : "false") +
            ",\"gpio\":4,\"uptime_ms\":" + String(millis()) +
            ",\"rssi\":" + String(WiFi.RSSI()) + ",\"ip\":\"" +
            WiFi.localIP().toString() +
            "\",\"sample_interval_ms\":" + String(ADC_SAMPLE_INTERVAL_MS) +
            ",\"adc_samples\":[";

  // oldestIndex 指向缓冲区内最早、应最先上报的采样值。
  const size_t oldestIndex =
      (adcWriteIndex + ADC_BUFFER_SIZE - adcSampleCount) % ADC_BUFFER_SIZE;
  // i 表示当前正在拼接第几个有效采样值。
  for (size_t i = 0; i < adcSampleCount; ++i) {
    if (i > 0) {
      payload += ',';
    }
    payload += String(adcSamples[(oldestIndex + i) % ADC_BUFFER_SIZE]);
  }
  payload += "]}";

  http.addHeader("Content-Type", "application/json");
  // responseCode 是 Flask 返回的 HTTP 状态码，例如成功时为 200。
  const int responseCode = http.POST(payload);
  // latestAdc 用于在串口打印本批数据中的最后一个 A0 值。
  const uint16_t latestAdc =
      adcSampleCount == 0
          ? 0
          : adcSamples[(adcWriteIndex + ADC_BUFFER_SIZE - 1) % ADC_BUFFER_SIZE];
  Serial.printf("LED=%s, ADC=%u, samples=%u, HTTP=%d\n",
                ledIsOn() ? "HIGH" : "LOW", latestAdc,
                static_cast<unsigned>(adcSampleCount), responseCode);
  if (responseCode >= 200 && responseCode < 300) {
    adcSampleCount = 0;
  }
  http.end();
}

// 上电后只执行一次：初始化串口、LED、Wi-Fi 和各定时基准。
void setup() {
  Serial.begin(UART0_BAUD_RATE);
  ledBegin(4);
  connectWiFi();
  // now 让不同定时任务从同一个启动时刻开始计时。
  const uint32_t now = millis();
  lastAdcSample = now;
  lastReport = now;
  reportStatus();
}

// 主循环只负责任务调度，具体 LED 和指令逻辑放在独立模块中。
void loop() {
  // now 是本轮循环统一使用的系统毫秒数。
  const uint32_t now = millis();
  sampleAdc(now);
  ledUpdateBlink(now);

  // targetState 用来接收 Flask 指令要求的 LED 目标状态。
  bool targetState = false;
  if (pollLedCommand(now, targetState)) {
    ledEnableRemoteControl();
    ledSet(targetState);
    Serial.printf("Remote LED command: %s\\n", targetState ? "ON" : "OFF");
  }

  if (now - lastReport >= REPORT_INTERVAL_MS) {
    lastReport = now;
    reportStatus();
  }

  if (WiFi.status() != WL_CONNECTED &&
      now - lastWiFiAttempt >= WIFI_RETRY_INTERVAL_MS) {
    lastWiFiAttempt = now;
    connectWiFi();
    reportStatus();
  }

  delay(1);
}
