// 这是厂家提供的独立点亮示例，仅用于查阅接线和基础 API。
// 正式项目由 tft_display.cpp 提供显示功能，因此这里不参与固件编译。
#if 0

#include <TFT_eSPI.h>  // 引入库

TFT_eSPI tft;  // 创建对象

  //引脚接线
//   clk D5
//   SDA D7
//   RS D3
//   RST D4
//   cs D8


void setup() {
  tft.init();               // 初始化屏幕
  tft.setRotation(0);       // 设置旋转方向（0-3）
  tft.fillScreen(TFT_BLACK); // 清屏为黑色

  // 显示文本
  tft.setTextColor(TFT_WHITE);
  tft.setTextSize(2);
  tft.setCursor(0, 0);
  tft.print("ESP8266");
  tft.setCursor(0, 30);
  tft.print("1.8 TFT");

  // 画图形
  tft.drawRect(10, 60, 100, 50, TFT_RED);    // 矩形
  tft.fillCircle(64, 140, 20, TFT_GREEN);    // 填充圆
}

void loop() {
  // 循环无操作
}

#endif
