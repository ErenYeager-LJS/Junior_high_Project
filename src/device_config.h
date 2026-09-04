#pragma once

#include <Arduino.h>

// 编译环境没有指定角色时，默认生成从机固件。
#ifndef DEVICE_ROLE_MASTER
#define DEVICE_ROLE_MASTER 0
#endif

// UART0 调试串口使用的波特率。
constexpr uint32_t UART0_BAUD_RATE = 921600;
// 电脑上 Flask 服务的局域网地址。
constexpr char SERVER_BASE_URL[] = "http://192.168.124.3:5000";
// 主机使用 D0，也就是 ESP8266 的 GPIO16。
constexpr uint8_t MASTER_LED_PIN = 16;
// 从机使用 GPIO4，对应开发板常见的 D2 引脚。
constexpr uint8_t SLAVE_LED_PIN = 4;
// 主机和从机的 LED 都在 GPIO 输出低电平时点亮。
constexpr bool MASTER_LED_ACTIVE_HIGH = false;
constexpr bool SLAVE_LED_ACTIVE_HIGH = false;
// 从机每 1000 us 读取一次 A0，目标采样率为 1000 Hz。
constexpr uint32_t ADC_SAMPLE_INTERVAL_US = 1000;
// 两块设备每 500 ms 向 Flask 上报一次自身状态。
constexpr uint32_t STATUS_REPORT_INTERVAL_MS = 500;
// 主机 TFT 每 500 ms 更新一次，避免频繁绘图占用主循环。
constexpr uint32_t TFT_REFRESH_INTERVAL_MS = 500;
// ESP8266 裸芯片 A0 的参考满量程为 1.0 V，用于屏幕电压换算。
constexpr float ADC_FULL_SCALE_VOLTAGE = 1.0F;
