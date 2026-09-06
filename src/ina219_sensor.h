#pragma once

#include <Arduino.h>

// 初始化从机 A 上的 INA219；返回 true 表示在 I2C 总线上找到传感器。
bool ina219Begin();

// 按固定周期读取一次电流，避免主循环反复访问 I2C。
void ina219Update(uint32_t nowMs);

// 返回最近一次有效电流，单位为毫安。
float ina219CurrentMa();

// 返回 INA219 当前是否已经初始化并读到有效数据。
bool ina219IsReady();
