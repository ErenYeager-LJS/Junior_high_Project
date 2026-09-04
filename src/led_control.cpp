#include "led_control.h"

namespace {
// 当前实际使用的 LED GPIO 编号，初始化前使用开发板默认值。
uint8_t ledPin = LED_BUILTIN;
// 软件记录的 LED 当前状态，true 表示高电平。
bool ledState = false;
// 是否已进入网页远程控制模式。
bool remoteControl = false;
// 自动闪烁最近一次翻转 LED 的系统毫秒数。
uint32_t lastChange = 0;
// 自动闪烁时，每隔 1000 ms 翻转一次。
constexpr uint32_t BLINK_INTERVAL_MS = 1000;
}

// 保存实际 GPIO 编号、配置输出模式，并让 LED 从关闭状态开始。
void ledBegin(uint8_t pin) {
  ledPin = pin;
  pinMode(ledPin, OUTPUT);
  ledSet(false);
  lastChange = millis();
}

// 同时更新软件状态和 GPIO 电平，避免网页显示与硬件不一致。
void ledSet(bool on) {
  ledState = on;
  digitalWrite(ledPin, on ? HIGH : LOW);
}

// 锁定为远程控制模式，避免自动闪烁覆盖网页下发的状态。
void ledEnableRemoteControl() { remoteControl = true; }

// 根据当前时间判断是否需要执行一次自动翻转。
void ledUpdateBlink(uint32_t now) {
  if (!remoteControl && now - lastChange >= BLINK_INTERVAL_MS) {
    lastChange = now;
    ledSet(!ledState);
  }
}

// 供状态上报模块读取当前 LED 状态。
bool ledIsOn() { return ledState; }
