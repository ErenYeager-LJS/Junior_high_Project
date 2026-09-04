#pragma once

#include <Arduino.h>

// 初始化 LED 引脚；activeHigh 表示高电平是否代表点亮。
void ledBegin(uint8_t pin, bool activeHigh);
// 立即把 LED 设置为打开或关闭。
void ledSet(bool on);
// 返回 LED 当前逻辑状态，true 始终表示灯亮。
bool ledIsOn();
