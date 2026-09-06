#include "device_config.h"

#if !DEVICE_ROLE_MASTER && DEVICE_SLAVE_INDEX == 0

#include "ina219_sensor.h"

#include <Adafruit_INA219.h>
#include <Wire.h>
#include <math.h>

namespace {
// ina219 是从机 A 上默认地址为 0x40 的电流传感器对象。
Adafruit_INA219 ina219;
// sensorReady 表示传感器已经通过初始化并能返回有效读数。
bool sensorReady = false;
// latestCurrentMa 保存最近一次有效电流，单位为毫安。
float latestCurrentMa = 0.0F;
// lastSampleMs 记录上次读取传感器的系统毫秒数。
uint32_t lastSampleMs = 0;
}

// 在 GPIO2/GPIO14 上启动 I2C，并使用 INA219 的 32 V、2 A 校准范围。
bool ina219Begin() {
  Wire.begin(INA219_SDA_PIN, INA219_SCL_PIN);
  sensorReady = ina219.begin();
  if (!sensorReady) return false;
  ina219.setCalibration_32V_2A();
  ina219Update(millis());
  return sensorReady;
}

// 每到采样周期读取一次电流；无效浮点值会把传感器标记为不可用。
void ina219Update(uint32_t nowMs) {
  if (!sensorReady || nowMs - lastSampleMs < INA219_SAMPLE_INTERVAL_MS) return;
  lastSampleMs = nowMs;
  // measuredCurrentMa 是 INA219 本次返回的分流电流，单位为毫安。
  const float measuredCurrentMa = ina219.getCurrent_mA();
  if (isnan(measuredCurrentMa) || isinf(measuredCurrentMa)) {
    sensorReady = false;
    return;
  }
  latestCurrentMa = measuredCurrentMa;
}

// 返回最近一次有效电流，供串口和网络状态上报使用。
float ina219CurrentMa() { return latestCurrentMa; }

// 返回传感器初始化和最近读数是否正常。
bool ina219IsReady() { return sensorReady; }

#endif
