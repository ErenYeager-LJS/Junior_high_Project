#pragma once

#include <Arduino.h>

// 初始化主机的 1.8 寸 TFT，并显示等待网络连接的启动画面。
void tftDisplayBegin();

// 定时刷新 Wi-Fi、A 从机 ADC、检测模式及 A/B/C 灯状态。
void tftDisplayUpdate(uint32_t now, uint16_t adcRaw, bool thresholdEnabled,
                      bool slaveLedA, bool slaveLedB, bool slaveLedC);
