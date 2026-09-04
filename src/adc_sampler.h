#pragma once

#include <Arduino.h>

// 初始化 A0 采样计时基准。
void adcBegin(uint32_t now);
// 到达采样时刻时读取一次 A0；now 是当前系统毫秒数。
void adcUpdate(uint32_t now);
// 返回当前缓冲区内有效采样的数量。
size_t adcCount();
// 按时间顺序读取第 index 个采样值。
uint16_t adcAt(size_t index);
// 返回最近一次 A0 原始值。
uint16_t adcLatest();
// 成功上报后清空已发送的采样值。
void adcClear();
