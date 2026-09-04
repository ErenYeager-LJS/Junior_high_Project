#include "led_control.h"

namespace {
// 当前实际使用的 LED GPIO 编号，初始化前使用开发板默认值。
uint8_t ledPin = LED_BUILTIN;
// 软件记录的 LED 当前逻辑状态，true 表示灯亮。
bool ledState = false;
// 保存当前硬件是高电平点亮还是低电平点亮。
bool ledActiveHigh = true;
}

// 保存引脚和有效电平，配置输出模式，并让灯从关闭状态开始。
void ledBegin(uint8_t pin, bool activeHigh) {
  ledPin = pin;
  ledActiveHigh = activeHigh;
  pinMode(ledPin, OUTPUT);
  ledSet(false);
}

// 根据有效电平换算实际 GPIO 输出，同时保存逻辑状态。
void ledSet(bool on) {
  ledState = on;
  const bool outputHigh = on == ledActiveHigh;
  digitalWrite(ledPin, outputHigh ? HIGH : LOW);
}

// 供状态上报模块读取当前 LED 状态。
bool ledIsOn() { return ledState; }
