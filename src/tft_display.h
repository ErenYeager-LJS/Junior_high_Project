#pragma once

#include <Arduino.h>

// 初始化主机的 1.8 寸 TFT，并显示等待网络连接的启动画面。
void tftDisplayBegin();

// 定时刷新 Wi-Fi、从机 ADC、阈值和主机 LED 信息；now 是当前系统毫秒数。
void tftDisplayUpdate(uint32_t now, uint16_t adcRaw, bool thresholdEnabled,
                      uint16_t thresholdRaw, bool ledOn);
