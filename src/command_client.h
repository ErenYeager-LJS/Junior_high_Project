#pragma once

#include <Arduino.h>

// 按设定周期从 Flask 取待执行指令。
// now 是当前系统毫秒数；targetState 用来带回目标 LED 状态。
// 返回 true 表示收到了有效指令，返回 false 表示本轮无需动作。
bool pollLedCommand(uint32_t now, bool& targetState);
