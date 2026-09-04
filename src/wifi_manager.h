#pragma once

#include <Arduino.h>

// 尝试连接项目配置的路由器，成功时返回 true。
bool wifiConnect();
// Wi-Fi 断开时按固定间隔重连；now 是当前系统毫秒数。
void wifiMaintain(uint32_t now);
