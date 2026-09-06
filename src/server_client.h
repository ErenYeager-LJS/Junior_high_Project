#pragma once

#include <Arduino.h>

// DeviceConfig 保存网页配置，以及主机需要的从机阈值状态。
struct DeviceConfig {
  // thresholdEnabled 为 true 时由 0.6 V 阈值自动控制灯。
  bool thresholdEnabled;
  // manualLed 是关闭阈值检测后，网页指定的灯状态。
  bool manualLed;
  // slaveOverThreshold 告诉主机从机电压是否超过阈值。
  bool slaveOverThreshold;
  // thresholdRaw 是服务端下发的 ADC 原始阈值。
  uint16_t thresholdRaw;
  // slaveAdcRaw 是服务端保存的从机最新 A0 原始值。
  uint16_t slaveAdcRaw;
  // slaveCurrentMa 是服务端转发给主机的从机 A 实时电流，单位为毫安。
  float slaveCurrentMa;
  // ina219Ready 表示从机 A 的 INA219 当前可以正常读数。
  bool ina219Ready;
  // automaticLed 是自动模式下所有从机跟随的 A 从机灯状态。
  bool automaticLed;
  // slaveLedA 保存 A 从机的实际灯状态，供主机 TFT 使用。
  bool slaveLedA;
  // slaveLedB 保存 B 从机的实际灯状态，供主机 TFT 使用。
  bool slaveLedB;
  // slaveLedC 保存 C 从机的实际灯状态，供主机 TFT 使用。
  bool slaveLedC;
  // tfCommandId 是 Flask 等待主机执行的 TF 卡模式命令编号。
  uint32_t tfCommandId;
  // tfCommandOperation 是新增或删除模式对应的英文操作名。
  String tfCommandOperation;
  // tfCommandRecord 是无需再次转义即可写入 TF 文件的紧凑模式记录。
  String tfCommandRecord;
};

// 从 Flask 获取指定角色的最新控制配置。
bool serverFetchConfig(const char* role, DeviceConfig& config);
// 从机上报状态和 INA219 读数，并从响应中更新控制配置。
bool serverReportSlave(bool ledOn, bool ina219Ready, float currentMa,
                       DeviceConfig& config);
// 主机上报状态和报警，并从响应中更新网页配置。
bool serverReportMaster(bool ledOn, bool alert, DeviceConfig& config);
