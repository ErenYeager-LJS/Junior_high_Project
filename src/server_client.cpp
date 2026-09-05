#include "server_client.h"

#include <ESP8266HTTPClient.h>
#include <ESP8266WiFi.h>
#include <WiFiClient.h>

#include "adc_sampler.h"
#include "device_config.h"
#if DEVICE_ROLE_MASTER
#include "tf_mode_store.h"
#endif

namespace {
// HTTP 请求最多等待 500 ms，超时后把执行权还给主循环。
constexpr uint16_t HTTP_TIMEOUT_MS = 500;

// 从简单 JSON 文本中读取布尔值；字段不存在时返回 fallback。
bool readBool(const String& body, const char* name, bool fallback) {
  // key 保存带双引号字段名的文本。
  const String key = String("\"") + name + "\"";
  // position 是字段名在 JSON 中的位置。
  const int position = body.indexOf(key);
  if (position < 0) return fallback;
  // colon 是字段名后冒号的位置。
  const int colon = body.indexOf(':', position + key.length());
  if (colon < 0) return fallback;
  // valueStart 跳过冒号后的空格，指向 true 或 false。
  int valueStart = colon + 1;
  while (valueStart < static_cast<int>(body.length()) && body[valueStart] == ' ') ++valueStart;
  if (body.indexOf("true", valueStart) == valueStart) return true;
  if (body.indexOf("false", valueStart) == valueStart) return false;
  return fallback;
}

// 从简单 JSON 文本中读取非负整数；字段不存在时返回 fallback。
uint16_t readUnsigned(const String& body, const char* name, uint16_t fallback) {
  // key 保存带双引号字段名的文本。
  const String key = String("\"") + name + "\"";
  // position 是字段名在 JSON 中的位置。
  const int position = body.indexOf(key);
  if (position < 0) return fallback;
  // colon 是字段名后冒号的位置。
  const int colon = body.indexOf(':', position + key.length());
  if (colon < 0) return fallback;
  return static_cast<uint16_t>(body.substring(colon + 1).toInt());
}

// 从简单 JSON 文本中读取不含引号和反斜杠的字符串字段。
String readString(const String& body, const char* name, const String& fallback) {
  // key 保存带双引号字段名的文本。
  const String key = String("\"") + name + "\"";
  // position 是字段名在 JSON 中的位置。
  const int position = body.indexOf(key);
  if (position < 0) return fallback;
  // colon 是字段名后冒号的位置。
  const int colon = body.indexOf(':', position + key.length());
  // quoteStart 和 quoteEnd 分别是字符串值两侧的双引号位置。
  const int quoteStart = body.indexOf('\"', colon + 1);
  const int quoteEnd = quoteStart < 0 ? -1 : body.indexOf('\"', quoteStart + 1);
  if (colon < 0 || quoteStart < 0 || quoteEnd < 0) return fallback;
  return body.substring(quoteStart + 1, quoteEnd);
}

// 把公共设备信息追加到正在构造的 JSON 文本中。
void appendCommonStatus(String& payload, const char* role, bool ledOn) {
  payload = String("{\"role\":\"") + role + "\",\"led\":" +
            (ledOn ? "true" : "false") + ",\"uptime_ms\":" + String(millis()) +
            ",\"rssi\":" + String(WiFi.RSSI()) + ",\"ip\":\"" +
            WiFi.localIP().toString() + "\"";
}

// 用响应 JSON 更新当前设备的控制配置。
void updateConfig(const String& body, DeviceConfig& config) {
  config.thresholdEnabled = readBool(body, "threshold_enabled", config.thresholdEnabled);
  config.manualLed = readBool(body, "manual_led", config.manualLed);
  config.slaveOverThreshold = readBool(body, "slave_over_threshold", config.slaveOverThreshold);
  config.thresholdRaw = readUnsigned(body, "threshold_raw", config.thresholdRaw);
  config.slaveAdcRaw = readUnsigned(body, "slave_adc_raw", config.slaveAdcRaw);
  config.automaticLed = readBool(body, "automatic_led", config.automaticLed);
  config.slaveLedA = readBool(body, "slave_a_led", config.slaveLedA);
  config.slaveLedB = readBool(body, "slave_b_led", config.slaveLedB);
  config.slaveLedC = readBool(body, "slave_c_led", config.slaveLedC);
  config.tfCommandId = readUnsigned(body, "tf_command_id", config.tfCommandId);
  config.tfCommandOperation = readString(body, "tf_command_operation", config.tfCommandOperation);
  config.tfCommandRecord = readString(body, "tf_command_record", config.tfCommandRecord);
}

// 向统一状态接口发送 JSON，并通过 responseBody 带回响应内容。
bool postStatus(const String& payload, String& responseBody) {
  if (WiFi.status() != WL_CONNECTED) return false;
  // client 提供 TCP 连接。
  WiFiClient client;
  // http 负责构造和发送 HTTP 请求。
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  // url 是设备状态接口的完整地址。
  const String url = String(SERVER_BASE_URL) + "/api/device-status";
  if (!http.begin(client, url)) return false;
  http.addHeader("Content-Type", "application/json");
  // code 保存服务端返回的 HTTP 状态码。
  const int code = http.POST(payload);
  if (code >= 200 && code < 300) responseBody = http.getString();
  http.end();
  return code >= 200 && code < 300;
}
}

// 请求对应角色的配置，并解析四个控制字段。
bool serverFetchConfig(const char* role, DeviceConfig& config) {
  if (WiFi.status() != WL_CONNECTED) return false;
  // client 提供 TCP 连接。
  WiFiClient client;
  // http 负责发送 GET 请求。
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  // url 把设备角色拼到配置接口末尾。
  const String url = String(SERVER_BASE_URL) + "/api/device-config/" + role;
  if (!http.begin(client, url)) return false;
  // code 保存服务端返回的 HTTP 状态码。
  const int code = http.GET();
  if (code != HTTP_CODE_OK) {
    http.end();
    return false;
  }
  // body 是 Flask 返回的 JSON 配置文本。
  const String body = http.getString();
  http.end();
  updateConfig(body, config);
  return true;
}

// 从机把环形缓冲区中的 ADC 数据按时间顺序写入 JSON 后发送。
bool serverReportSlave(bool ledOn, DeviceConfig& config) {
  // payload 保存本次 POST 的完整 JSON 文本。
  String payload;
  payload.reserve(3500);
  // roleName 根据编译编号区分 A、B、C 三块从机。
#if DEVICE_SLAVE_INDEX == 0
  const char* roleName = "slave_a";
#elif DEVICE_SLAVE_INDEX == 1
  const char* roleName = "slave_b";
#else
  const char* roleName = "slave_c";
#endif
  appendCommonStatus(payload, roleName, ledOn);
#if DEVICE_SLAVE_INDEX == 0
  payload += ",\"sample_interval_us\":" + String(ADC_SAMPLE_INTERVAL_US) + ",\"adc_samples\":[";
  // count 固定本次要发送的数量，避免循环期间变化。
  const size_t count = adcCount();
  // index 表示当前追加的是第几个采样值。
  for (size_t index = 0; index < count; ++index) {
    if (index > 0) payload += ',';
    payload += String(adcAt(index));
  }
  payload += "]}";
#else
  // B、C 暂不使用 ADC，只发送灯状态和在线信息。
  payload += "}";
#endif
  // responseBody 接收 Flask 随状态响应返回的最新控制配置。
  String responseBody;
  // success 表示服务端是否确认接收。
  const bool success = postStatus(payload, responseBody);
  if (success) {
    adcClear();
    updateConfig(responseBody, config);
  }
  return success;
}

// 主机不带 ADC 数据，只上报 D0 和报警信息。
bool serverReportMaster(bool ledOn, bool alert, DeviceConfig& config) {
  // payload 保存本次 POST 的完整 JSON 文本。
  String payload;
  payload.reserve(256);
  appendCommonStatus(payload, "master", ledOn);
  payload += String(",\"alert\":") + (alert ? "true" : "false");
#if DEVICE_ROLE_MASTER
  payload += String(",\"tf_card_ready\":") + (tfModeStoreReady() ? "true" : "false");
  payload += ",\"tf_modes_data\":\"" + tfModeStoreEncodedModes() + "\"";
  payload += ",\"tf_command_ack\":" + String(tfModeStoreAcknowledgedCommandId());
  payload += String(",\"tf_command_success\":") +
             (tfModeStoreLastCommandSucceeded() ? "true" : "false");
#endif
  payload += "}";
  // responseBody 接收 Flask 随状态响应返回的最新控制配置。
  String responseBody;
  // success 表示服务端是否确认接收。
  const bool success = postStatus(payload, responseBody);
  if (success) updateConfig(responseBody, config);
  return success;
}
