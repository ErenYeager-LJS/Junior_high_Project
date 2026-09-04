#include "command_client.h"

#include <ESP8266HTTPClient.h>
#include <ESP8266WiFi.h>
#include <WiFiClient.h>

namespace {
// ESP8266 从这个 Flask 接口读取网页下发的 LED 指令。
constexpr char COMMAND_URL[] = "http://192.168.124.3:5000/api/command";
// 每隔 250 ms 查询一次，兼顾响应速度和局域网负载。
constexpr uint32_t POLL_INTERVAL_MS = 250;
// 最近一次查询指令的系统毫秒数。
uint32_t lastPoll = 0;
}

// 查询服务端并解析 JSON 中的 led 布尔值。
bool pollLedCommand(uint32_t now, bool& targetState) {
  if (now - lastPoll < POLL_INTERVAL_MS || WiFi.status() != WL_CONNECTED) {
    return false;
  }
  lastPoll = now;

  // client 建立 TCP 连接，http 负责发送 GET 请求。
  WiFiClient client;
  HTTPClient http;
  http.setTimeout(250);
  if (!http.begin(client, COMMAND_URL)) return false;
  // code 保存服务端返回的 HTTP 状态码。
  const int code = http.GET();
  if (code != HTTP_CODE_OK) {
    http.end();
    return false;
  }

  // body 是 Flask 返回的 JSON 文本，例如 {"id":1,"led":true}。
  const String body = http.getString();
  http.end();
  // Flask 返回 {} 表示暂时没有新指令；有 led 字段才执行。
  // key 是 JSON 中 led 字段名的起始位置。
  const int key = body.indexOf("\"led\"");
  if (key < 0) return false;
  // colon 是 led 字段名后冒号的位置，用它定位布尔值。
  const int colon = body.indexOf(':', key);
  if (colon < 0) return false;
  if (body.indexOf("true", colon) == colon + 1) {
    targetState = true;
    return true;
  }
  if (body.indexOf("false", colon) == colon + 1) {
    targetState = false;
    return true;
  }
  return false;
}
