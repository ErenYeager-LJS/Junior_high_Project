#pragma once

#include <Arduino.h>

// 初始化主机的 1.8 寸 TFT，并显示等待网络连接的启动画面。
void tftDisplayBegin();

// 短暂显示 TF 卡挂载、读写、容量和根目录统计结果。
void tftDisplayShowTfCardTest(bool mounted, bool readWritePassed,
                              uint32_t capacityMb, uint16_t rootEntryCount);

// 定时刷新 Wi-Fi、INA219 电流、检测模式及 A/B/C 灯状态。
void tftDisplayUpdate(uint32_t now, float currentMa, bool ina219Ready,
                      bool thresholdEnabled, bool slaveLedA,
                      bool slaveLedB, bool slaveLedC);
