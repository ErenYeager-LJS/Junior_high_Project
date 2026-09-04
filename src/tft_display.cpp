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
  drawStatusLine(27, "WiFi: ", "CONNECTING", TFT_YELLOW);
  displayReady = true;
}

// 每到刷新周期，重绘六项实时状态；其余主循环不操作屏幕。
void tftDisplayUpdate(uint32_t now, uint16_t adcRaw, bool thresholdEnabled,
                      uint16_t thresholdRaw, bool ledOn) {
  if (!displayReady || now - lastRefreshMs < TFT_REFRESH_INTERVAL_MS) return;
  lastRefreshMs = now;

  // wifiConnected 表示从机当前是否已连上路由器。
  const bool wifiConnected = WiFi.status() == WL_CONNECTED;
  // adcVoltage 是最近一次 A0 样本换算后的电压。
  const float adcVoltage = rawToVoltage(adcRaw);
  // thresholdVoltage 是网页设置的 ADC 阈值换算后的电压。
  const float thresholdVoltage = rawToVoltage(thresholdRaw);
  // overThreshold 表示当前采样是否高于网页设置的阈值。
  const bool overThreshold = adcRaw > thresholdRaw;

  drawStatusLine(27, "WiFi: ", wifiConnected ? "ONLINE" : "OFFLINE",
                 wifiConnected ? TFT_GREEN : TFT_RED);
  drawStatusLine(50, "A0: ", String(adcVoltage, 3) + " V", TFT_WHITE);
  drawStatusLine(73, "Detect: ", thresholdEnabled ? "ON" : "OFF",
                 thresholdEnabled ? TFT_GREEN : TFT_YELLOW);
  drawStatusLine(96, "Limit: ", String(thresholdVoltage, 3) + " V", TFT_WHITE);
  drawStatusLine(119, "Level: ", overThreshold ? "OVER" : "NORMAL",
                 overThreshold ? TFT_RED : TFT_GREEN);
  drawStatusLine(142, "LED: ", ledOn ? "ON" : "OFF",
                 ledOn ? TFT_GREEN : TFT_LIGHTGREY);
}

#endif
