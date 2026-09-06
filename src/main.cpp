#include <Arduino.h>

#include "device_config.h"
#if !DEVICE_ROLE_MASTER && DEVICE_SLAVE_INDEX == 0
#include "ina219_sensor.h"
#endif
#include "led_control.h"
#include "server_client.h"
#if DEVICE_ROLE_MASTER
#include "tft_display.h"
#include "tf_card_test.h"
#include "tf_mode_store.h"
#endif
#include "wifi_manager.h"

namespace {
// config 保存网页下发的阈值开关、手动灯状态和从机阈值结果。
DeviceConfig config = {true, false, false, 614, 0, 0.0F, false,
                       false, false, false, false, 0, "", ""};
// lastStatusReport 记录上次上报本机状态的系统毫秒数。
uint32_t lastStatusReport = 0;
}

// 根据当前编译角色初始化对应的 LED、INA219 和网络。
void setup() {
  Serial.begin(UART0_BAUD_RATE);
#if DEVICE_ROLE_MASTER
  ledBegin(MASTER_LED_PIN, MASTER_LED_ACTIVE_HIGH);
  tftDisplayBegin();
  // tfCardResult 保存本次开机挂载、读写和清理测试的完整结果。
  const TfCardTestResult tfCardResult = tfCardRunSelfTest();
  tftDisplayShowTfCardTest(tfCardResult.mounted, tfCardResult.readWritePassed,
                           tfCardResult.capacityMb, tfCardResult.rootEntryCount);
  tfModeStoreBegin(tfCardResult.mounted && tfCardResult.readWritePassed);
  Serial.println("Role: master, LED: D0/GPIO16 active LOW");
#else
  ledBegin(SLAVE_LED_PIN, SLAVE_LED_ACTIVE_HIGH);
#if DEVICE_SLAVE_INDEX == 0
  // 从机 A 按实物接线初始化 GPIO2/GPIO14 上的 INA219。
  const bool inaReady = ina219Begin();
  Serial.println("Role: slave A, INA219 SDA=GPIO2 SCL=GPIO14, LED: GPIO4 active LOW");
  Serial.println(inaReady ? "[INA219] READY at 0x40" : "[INA219] NOT FOUND");
#elif DEVICE_SLAVE_INDEX == 1
  Serial.println("Role: slave B, LED: GPIO4 active LOW, ADC: disabled");
#else
  Serial.println("Role: slave C, LED: GPIO4 active LOW, ADC: disabled");
#endif
#endif
  wifiConnect();
}

// 主循环按固定周期读取配置、执行控制逻辑并上报状态。
void loop() {
  // now 是本轮所有定时任务共用的系统毫秒数。
  const uint32_t now = millis();
  wifiMaintain(now);

#if DEVICE_ROLE_MASTER
  // 自动模式跟随从机阈值；手动模式使用网页指定状态。
  const bool masterLedTarget = config.thresholdEnabled ? config.slaveOverThreshold : config.manualLed;
  ledSet(masterLedTarget);
  // 主机 TFT 显示服务端返回的 A0、阈值、网络和四盏灯状态。
  tftDisplayUpdate(now, config.slaveCurrentMa, config.ina219Ready,
                   config.thresholdEnabled,
                   config.slaveLedA, config.slaveLedB, config.slaveLedC);
  // 只有自动模式且超过阈值时，主机才向网页报告警消息。
  const bool alertActive = config.thresholdEnabled && config.slaveOverThreshold;
  if (now - lastStatusReport >= STATUS_REPORT_INTERVAL_MS) {
    lastStatusReport = now;
    serverReportMaster(ledIsOn(), alertActive, config);
    tfModeStoreHandleCommand(config.tfCommandId, config.tfCommandOperation,
                             config.tfCommandRecord);
  }
#else
#if DEVICE_SLAVE_INDEX == 0
  // 从机 A 周期读取 INA219，同时保留原有 GPIO4 LED 控制。
  ina219Update(now);
#endif
  // 三个从机仍按原有自动或手动模式控制低电平 LED。
  const bool slaveLedTarget = config.thresholdEnabled ? config.automaticLed : config.manualLed;
  ledSet(slaveLedTarget);
  if (now - lastStatusReport >= STATUS_REPORT_INTERVAL_MS) {
    lastStatusReport = now;
#if DEVICE_SLAVE_INDEX == 0
    // currentMa 是本轮即将打印并上报的 INA219 实时电流。
    const float currentMa = ina219CurrentMa();
    Serial.print("[INA219] Current: ");
    Serial.print(currentMa, 2);
    Serial.println(" mA");
    serverReportSlave(ledIsOn(), ina219IsReady(), currentMa, config);
#else
    serverReportSlave(ledIsOn(), false, 0.0F, config);
#endif
  }
#endif

  // 主机没有高速采样任务，可以每轮让出 1 ms。
#if DEVICE_ROLE_MASTER
  delay(1);
#else
  // 从机不额外延时；ESP8266 Arduino 核心会在 loop 返回后按需运行 Wi-Fi。
  // 这样 1000 us 采样周期不会再叠加固定的 1 ms 延迟。
#endif
}
