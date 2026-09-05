#include "device_config.h"

#if DEVICE_ROLE_MASTER

#include "tft_display.h"

#include <ESP8266WiFi.h>
#include <TFT_eSPI.h>

namespace {
// tft 是 TFT_eSPI 库提供的屏幕控制对象。
TFT_eSPI tft;
// lastRefreshMs 记录上次刷新屏幕的系统毫秒数。
uint32_t lastRefreshMs = 0;
// displayReady 表示屏幕初始化已经完成，可以接收绘图命令。
bool displayReady = false;

// 把 10 位 ADC 原始值换算为当前项目使用的电压值。
float rawToVoltage(uint16_t raw) {
  return static_cast<float>(raw) * ADC_FULL_SCALE_VOLTAGE / 1023.0F;
}

// 在指定纵坐标覆盖绘制一整行，避免新旧文字重叠。
void drawStatusLine(int16_t y, const String& label, const String& value,
                    uint16_t valueColor) {
  // lineHeight 是 Font 2 字体对应的单行清除高度。
  constexpr int16_t lineHeight = 21;
  tft.fillRect(0, y, tft.width(), lineHeight, TFT_BLACK);
  tft.setTextFont(2);
  tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  tft.setCursor(2, y + 2);
  tft.print(label);
  tft.setTextColor(valueColor, TFT_BLACK);
  tft.print(value);
}
}

// 初始化竖屏界面，并先显示主机正在连接网络。
void tftDisplayBegin() {
  tft.init();
  tft.setRotation(0);
  tft.fillScreen(TFT_BLACK);
  tft.setTextFont(2);
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.setCursor(2, 2);
  tft.print("MASTER MONITOR");
  tft.drawFastHLine(0, 21, tft.width(), TFT_DARKGREY);
  drawStatusLine(25, "WiFi: ", "CONNECTING", TFT_YELLOW);
  displayReady = true;
}

// 每到刷新周期，重绘六项实时状态；其余主循环不操作屏幕。
void tftDisplayUpdate(uint32_t now, uint16_t adcRaw, bool thresholdEnabled,
                      bool slaveLedA, bool slaveLedB, bool slaveLedC) {
  if (!displayReady || now - lastRefreshMs < TFT_REFRESH_INTERVAL_MS) return;
  lastRefreshMs = now;

  // wifiConnected 表示从机当前是否已连上路由器。
  const bool wifiConnected = WiFi.status() == WL_CONNECTED;
  // adcVoltage 是最近一次 A0 样本换算后的电压。
  const float adcVoltage = rawToVoltage(adcRaw);
  drawStatusLine(25, "WiFi: ", wifiConnected ? "ONLINE" : "OFFLINE",
                 wifiConnected ? TFT_GREEN : TFT_RED);
  drawStatusLine(48, "A0: ", String(adcVoltage, 3) + " V", TFT_WHITE);
  drawStatusLine(71, "Detect: ", thresholdEnabled ? "ON" : "OFF",
                 thresholdEnabled ? TFT_GREEN : TFT_YELLOW);
  drawStatusLine(94, "A LED: ", slaveLedA ? "ON" : "OFF",
                 slaveLedA ? TFT_GREEN : TFT_LIGHTGREY);
  drawStatusLine(117, "B LED: ", slaveLedB ? "ON" : "OFF",
                 slaveLedB ? TFT_GREEN : TFT_LIGHTGREY);
  drawStatusLine(140, "C LED: ", slaveLedC ? "ON" : "OFF",
                 slaveLedC ? TFT_GREEN : TFT_LIGHTGREY);
}

#endif
