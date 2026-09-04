# ESP8266 项目交接日志

## 2026-09-04

### 当前功能

- ESP8266 连接路由器，并向 Flask 服务上报 GPIO4、设备 IP、RSSI、运行时间和 A0 原始采样值。
- GPIO4 默认每秒翻转一次；收到网页远程指令后进入远程控制模式。
- A0 配置为 4 ms 一次采样，服务端按 250 Hz 显示最近 15 秒波形。
- Flask 页面显示设备在线状态、GPIO4 状态、A0 当前值、最小值、最大值和波形。
- Flask 页面提供 GPIO4“打开、关闭、翻转”按钮。

### 远程控制链路

网页向 `POST /api/command` 发送 `{"action":"on"}`、`{"action":"off"}` 或 `{"action":"toggle"}`。

ESP8266 每 250 ms 请求 `GET /api/command`。服务端返回待执行 LED 状态后，设备设置 GPIO4，并通过下一次 `POST /api/status` 回报结果。服务端收到目标状态后清除待执行指令。

### 源码结构

- `src/main.cpp`：系统初始化、任务调度、Wi-Fi、ADC 采样和状态上报。
- `src/led_control.h/.cpp`：GPIO4 初始化、自动闪烁、远程控制状态。
- `src/command_client.h/.cpp`：从 Flask 轮询并解析 LED 指令。
- `server/app.py`：Flask 页面、状态接口、波形缓存和指令接口。
- `server/templates/index.html`：页面结构和 GPIO4 控制按钮。
- `server/static/app.js`：状态轮询、波形绘制和指令发送。
- `server/static/styles.css`：页面布局和控件样式。

### 已验证事项

- PlatformIO 编译成功，目标板为 ESP8266 ESP-12E。
- 固件已通过 `COM9` 下载，上传速率为 921600。
- ESP8266 实测地址为 `192.168.124.11`，电脑 Flask 地址为 `192.168.124.3:5000`。
- 服务端接口测试通过：`on`、`off` 指令返回 200，无效 action 返回 400。
- 真实硬件闭环测试通过：服务端下发 `off` 后设备回报低电平，下发 `on` 后设备回报高电平。

### 启动方法

在项目根目录执行：

```powershell
cd server
.\.venv\Scripts\python.exe app.py
```

保持该 PowerShell 窗口打开，然后访问 `http://192.168.124.3:5000/`。电脑和 ESP8266 必须连接同一路由器。

### 交接注意事项

- `include/wifi_secrets.h` 含 Wi-Fi 配置，已由 `.gitignore` 排除，不要提交到公开仓库。
- 修改 Flask 监听端口或电脑 IP 后，要同步修改 `src/main.cpp` 的状态地址和 `src/command_client.cpp` 的指令地址。
- 修改固件后，在项目根目录执行 `platformio run` 编译；确认无误后执行 `platformio run --target upload` 下载。
- 项目临时文件、编译缓存和测试日志放在 `buffer/`，不要把这些文件移到 C 盘临时目录。
