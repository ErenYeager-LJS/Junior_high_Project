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

// 在开机阶段显示 TF 卡自检结果，方便不接电脑时直接看屏幕判断。
void tftDisplayShowTfCardTest(bool mounted, bool readWritePassed,
                              uint32_t capacityMb, uint16_t rootEntryCount) {
  if (!displayReady) return;
  // passed 只有挂载和临时文件读写都成功时才为 true。
  const bool passed = mounted && readWritePassed;
  tft.fillScreen(TFT_BLACK);
  tft.setTextFont(2);
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.setCursor(2, 2);
  tft.print("TF CARD TEST");
  tft.drawFastHLine(0, 21, tft.width(), TFT_DARKGREY);
  drawStatusLine(30, "Mount: ", mounted ? "OK" : "FAIL",
                 mounted ? TFT_GREEN : TFT_RED);
  drawStatusLine(55, "R/W: ", readWritePassed ? "OK" : "FAIL",
                 readWritePassed ? TFT_GREEN : TFT_RED);
  drawStatusLine(80, "Size: ", mounted ? String(capacityMb) + " MB" : "--",
                 mounted ? TFT_WHITE : TFT_LIGHTGREY);
  drawStatusLine(105, "Files: ", mounted ? String(rootEntryCount) : "--",
                 mounted ? TFT_WHITE : TFT_LIGHTGREY);
  drawStatusLine(130, "Result: ", passed ? "PASS" : "FAIL",
                 passed ? TFT_GREEN : TFT_YELLOW);
  delay(3500);
  // 自检结束后重画正式监测页的固定标题。
  tft.fillScreen(TFT_BLACK);
  tft.setTextFont(2);
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.setCursor(2, 2);
  tft.print("MASTER MONITOR");
  tft.drawFastHLine(0, 21, tft.width(), TFT_DARKGREY);
}

// 每到刷新周期，重绘六项实时状态；其余主循环不操作屏幕。
void tftDisplayUpdate(uint32_t now, float currentMa, bool ina219Ready,
                      bool thresholdEnabled, bool slaveLedA,
                      bool slaveLedB, bool slaveLedC) {
  if (!displayReady || now - lastRefreshMs < TFT_REFRESH_INTERVAL_MS) return;
  lastRefreshMs = now;

  // wifiConnected 表示从机当前是否已连上路由器。
  const bool wifiConnected = WiFi.status() == WL_CONNECTED;
  drawStatusLine(25, "WiFi: ", wifiConnected ? "ONLINE" : "OFFLINE",
                 wifiConnected ? TFT_GREEN : TFT_RED);
  // currentText 在传感器正常时显示安培值，否则明确显示未连接。
  const String currentText = ina219Ready ? String(currentMa / 1000.0F, 3) + " A" : "NO SENSOR";
  drawStatusLine(48, "Current: ", currentText,
                 ina219Ready ? TFT_WHITE : TFT_RED);
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
