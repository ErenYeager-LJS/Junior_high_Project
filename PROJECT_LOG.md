# ESP8266 项目交接日志

## 2026-09-04：双机阈值监测版本

### 设备分工

- 主机编译环境为 `master`，预留下载端口 `COM10`。主机通过 Flask 读取从机阈值状态，控制 D0/GPIO16 LED，高电平点亮。
- 从机编译环境为 `slave`，预留下载端口 `COM11`。从机读取 A0，控制 GPIO4 LED，低电平点亮。
- 两块设备不直接用串口通信。它们连接同一路由器，通过电脑上的 Flask 服务交换状态和配置。

### 控制规则

- 阈值检测开启时，从机将 A0 与 0.600 V 阈值比较。超过阈值后，从机 GPIO4 灯点亮；主机从 Flask 取得结果后点亮 D0，并上报“电压大于阈值”。
- 阈值检测关闭时，网页可以分别打开或关闭主机、从机的 LED。
- 自动模式下服务端拒绝手动 LED 指令，避免两套控制逻辑互相覆盖。
- 当前按 ESP8266 A0 满量程 1.0 V、10 位 ADC 换算，0.600 V 对应原始值 614。若开发板 A0 前端自带分压，必须按实际板卡量程修改换算关系。

### 新的源码模块

- `src/device_config.h`：主从角色、引脚、电平极性、采样和通信周期。
- `src/wifi_manager.h/.cpp`：路由器连接和断线重连。
- `src/adc_sampler.h/.cpp`：从机 A0 定时采样和环形缓冲。
- `src/led_control.h/.cpp`：统一处理高电平或低电平点亮的 LED。
- `src/server_client.h/.cpp`：读取 Flask 配置并上报主机或从机状态。
- `src/main.cpp`：根据 `DEVICE_ROLE_MASTER` 编译主机或从机任务调度代码。

### 编译与验证

- `platformio run -e master -e slave` 编译通过。
- 主机固件：RAM 35.0%，Flash 27.6%。
- 从机固件：RAM 35.3%，Flash 27.6%。
- 本次按要求没有向 COM10 或 COM11 下载固件，因此真实双机联动尚未验证。
- Flask 接口模拟通过：A0 原始值 500 未超阈值，700 超过阈值；自动模式拒绝手动指令，关闭阈值后允许分别控制设备。
- 网页已在 320、375、414、768、1280 px 宽度检查，无横向滚动。

### 编译命令

```powershell
platformio run -e master
platformio run -e slave
```

下载时必须明确指定环境，避免把角色烧错：主机使用 `platformio run -e master --target upload`，从机使用 `platformio run -e slave --target upload`。

### 如何切换主机和从机

项目只有一个 `src/main.cpp`，不需要手动替换文件。`platformio.ini` 中的两个编译环境会传入不同的预处理标志：

- `[env:master]` 传入 `DEVICE_ROLE_MASTER=1`，编译 `main.cpp` 中 `#if DEVICE_ROLE_MASTER` 下的主机代码。
- `[env:slave]` 传入 `DEVICE_ROLE_MASTER=0`，编译 `#else` 下的从机代码。

在 VS Code 左侧打开 PlatformIO，进入 `PROJECT TASKS`，选择 `master` 或 `slave`，再点对应环境下的 `Build`。以后需要下载时，也必须在对应环境下点 `Upload`。

不带 `-e` 执行 `platformio run` 时，因为 `default_envs = master, slave`，PlatformIO 会把两个固件都编译一遍。

两个板同时连接时，执行 `platformio run --target upload` 会按 `default_envs` 的顺序处理两个环境：先用 `DEVICE_ROLE_MASTER=1` 生成主机固件并写入 COM10，再用 `DEVICE_ROLE_MASTER=0` 生成从机固件并写入 COM11。PlatformIO 不会自动判断板子的角色，角色完全由环境标志和端口绑定决定。

第一次下载建议分开执行：

```powershell
platformio run -e master --target upload
platformio run -e slave --target upload
```

下载前应在 Windows 设备管理器或 PlatformIO Devices 中确认主机仍是 COM10、从机仍是 COM11。更换 USB 插口或驱动后，COM 编号可能变化；端口写反会把两块板的角色固件烧反。

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
