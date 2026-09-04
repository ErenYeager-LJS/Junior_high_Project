#pragma once

#include <Arduino.h>

// 初始化 LED 引脚，并默认输出低电平。
void ledBegin(uint8_t pin);
// 在尚未收到远程指令时，每秒自动翻转一次 LED。
void ledUpdateBlink(uint32_t now);
// 立即把 LED 设置为打开或关闭。
void ledSet(bool on);
// 返回 LED 当前状态，true 表示高电平。
bool ledIsOn();
// 收到首条远程指令后，停止自动闪烁并改由网页控制。
void ledEnableRemoteControl();
