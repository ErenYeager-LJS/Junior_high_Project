#include <Arduino.h>

#include "adc_sampler.h"
#include "device_config.h"
#include "led_control.h"
#include "server_client.h"
#include "wifi_manager.h"

namespace {
// config 保存网页下发的阈值开关、手动灯状态和从机阈值结果。
DeviceConfig config = {true, false, false, 614};
// lastConfigPoll 记录上次读取网页配置的系统毫秒数。
uint32_t lastConfigPoll = 0;
// lastStatusReport 记录上次上报本机状态的系统毫秒数。
uint32_t lastStatusReport = 0;
}

// 根据当前编译角色初始化对应的 LED、ADC 和网络。
void setup() {
  Serial.begin(UART0_BAUD_RATE);
#if DEVICE_ROLE_MASTER
  ledBegin(MASTER_LED_PIN, MASTER_LED_ACTIVE_HIGH);
  Serial.println("Role: master, LED: D0/GPIO16 active HIGH");
#else
  ledBegin(SLAVE_LED_PIN, SLAVE_LED_ACTIVE_HIGH);
  adcBegin(millis());
  Serial.println("Role: slave, LED: GPIO4 active LOW, ADC: A0");
#endif
  wifiConnect();
}

// 主循环按固定周期读取配置、执行控制逻辑并上报状态。
void loop() {
  // now 是本轮所有定时任务共用的系统毫秒数。
  const uint32_t now = millis();
  wifiMaintain(now);

#if DEVICE_ROLE_MASTER
  // 主机每 250 ms 获取从机是否超过阈值，以及网页手动命令。
  if (now - lastConfigPoll >= CONFIG_POLL_INTERVAL_MS) {
    lastConfigPoll = now;
    serverFetchConfig("master", config);
  }
  // 自动模式跟随从机阈值；手动模式使用网页指定状态。
  const bool masterLedTarget = config.thresholdEnabled ? config.slaveOverThreshold : config.manualLed;
  ledSet(masterLedTarget);
  // 只有自动模式且超过阈值时，主机才向网页报告警消息。
  const bool alertActive = config.thresholdEnabled && config.slaveOverThreshold;
  if (now - lastStatusReport >= STATUS_REPORT_INTERVAL_MS) {
    lastStatusReport = now;
    serverReportMaster(ledIsOn(), alertActive);
  }
#else
  // 从机持续采集 A0，数据由 adc_sampler 模块暂存。
  adcUpdate(now);
  // 从机每 250 ms 获取阈值开关、阈值和网页手动命令。
  if (now - lastConfigPoll >= CONFIG_POLL_INTERVAL_MS) {
    lastConfigPoll = now;
    serverFetchConfig("slave", config);
  }
  // 自动模式直接比较本机 ADC；从机灯是低电平触发，但模块会自动换算电平。
  const bool slaveLedTarget = config.thresholdEnabled ? adcLatest() > config.thresholdRaw : config.manualLed;
  ledSet(slaveLedTarget);
  if (now - lastStatusReport >= STATUS_REPORT_INTERVAL_MS) {
    lastStatusReport = now;
    serverReportSlave(ledIsOn());
  }
#endif

  // 短暂让出 CPU，保证 ESP8266 的 Wi-Fi 协议栈能够运行。
  delay(1);
}
