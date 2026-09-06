from collections import deque
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from threading import Lock
from time import time
from urllib.parse import quote, unquote

from flask import Flask, jsonify, render_template, request, send_from_directory

try:
    # 直接运行 app.py 时使用同目录导入。
    from deepseek_assistant import (
        AssistantError,
        request_control_plan,
        request_weather_reply,
        validate_control_plan,
    )
    from weather_service import WeatherError, get_current_weather
except ImportError:
    # 作为 server.app 导入测试时使用包内相对导入。
    from .deepseek_assistant import (
        AssistantError,
        request_control_plan,
        request_weather_reply,
        validate_control_plan,
    )
    from .weather_service import WeatherError, get_current_weather


# PROJECT_ROOT 是包含网页令牌和固件源码的项目根目录。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# ONLINE_WINDOW_SECONDS 表示设备超过多少秒未上报后显示为离线。
ONLINE_WINDOW_SECONDS = 4
# ADC_MAX_VALUE 是 ESP8266 十位 ADC 的最大原始值。
ADC_MAX_VALUE = 1023
# ADC_REFERENCE_VOLTAGE 是当前开发板 A0 换算使用的满量程电压。
ADC_REFERENCE_VOLTAGE = 1.0
# THRESHOLD_VOLTAGE 是自动联动 LED 的电压阈值。
THRESHOLD_VOLTAGE = 0.6
# THRESHOLD_RAW 是电压阈值换算后的 ADC 原始值。
THRESHOLD_RAW = round(THRESHOLD_VOLTAGE / ADC_REFERENCE_VOLTAGE * ADC_MAX_VALUE)
# ADC_HISTORY_POINTS 是服务端最多保留的原始波形点数。
ADC_HISTORY_POINTS = 20000
# WAVEFORM_DISPLAY_POINTS 是单次发给网页绘图的最大点数。
WAVEFORM_DISPLAY_POINTS = 2000
# DEVICE_ROLES 是服务端认可的四种设备身份。
DEVICE_ROLES = ("master", "slave_a", "slave_b", "slave_c")
# DEFAULT_TF_MODES 是主机首次同步前供网页显示的两个基础模式。
DEFAULT_TF_MODES = {
    "mode_1": {"id": "mode_1", "name": "模式 1",
               "led_states": {"master": False, "slave_a": True, "slave_b": True, "slave_c": True}},
    "mode_2": {"id": "mode_2", "name": "模式 2",
               "led_states": {"master": True, "slave_a": False, "slave_b": False, "slave_c": False}},
}
# MAX_TF_MODES 是 TF 卡中允许保存的最大模式数量。
MAX_TF_MODES = 12
# MAX_MODE_NAME_LENGTH 是网页模式名称允许的最大字符数。
MAX_MODE_NAME_LENGTH = 24
# MAX_MODE_DURATION_SECONDS 是单次模式最长持续时间。
MAX_MODE_DURATION_SECONDS = 3600
# 单个访问端在 60 秒内最多发起 10 次 AI 请求。
ASSISTANT_RATE_LIMIT = 10
# AI 请求限流窗口长度，单位为秒。
ASSISTANT_RATE_WINDOW_SECONDS = 60
# LOCAL_TIME_ZONE 是网页助手回答日期和时间时采用的中国标准时区。
LOCAL_TIME_ZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")

# app 是 Flask Web 服务实例。
app = Flask(__name__)
# state_lock 防止设备上报与网页命令同时修改共享状态。
state_lock = Lock()
# devices 保存四块 ESP8266 最近一次上报的数据。
devices = {
    role: {
        "led": None, "last_seen_epoch": None, "device_ip": None,
        "rssi": None, "uptime_ms": None, "adc_latest": None,
        "sample_interval_us": None, "current_ma": None,
        "ina219_ready": False, "alert": False,
    }
    for role in DEVICE_ROLES
}
# control 保存当前控制模式和每块板的手动 LED 目标状态。
control = {"threshold_enabled": True, "manual_led": {role: False for role in DEVICE_ROLES}}
# adc_waveform 按时间保存 A 从机最近的 ADC 原始采样点。
adc_waveform = deque(maxlen=ADC_HISTORY_POINTS)
# adc_batches 保存近期采样批次，用于估算服务端实收采样率。
adc_batches = deque(maxlen=30)
# events 保存最近的模式切换和 LED 状态变化记录。
events = deque(maxlen=20)
# assistant_requests 按访问端 IP 保存最近的 AI 请求时间。
assistant_requests = {}
# tf_mode_state 保存主机 TF 卡同步出的模式和当前待执行写卡命令。
tf_mode_state = {
    "card_ready": False,
    "modes": {mode_id: dict(mode) for mode_id, mode in DEFAULT_TF_MODES.items()},
    "pending_command": None,
    "next_command_id": 1,
    "last_write_error": None,
}
# timed_mode 保存当前临时模式名称和自动结束时间。
timed_mode = {"id": None, "name": None, "deadline": None}


# utc_label 把 Unix 时间戳转换成网页可以解析的 UTC 文本。
def utc_label(epoch_seconds):
    if epoch_seconds is None:
        return None
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).isoformat()


# public_device 复制指定设备状态，并补充上报时间和在线判断。
def public_device(role, now):
    # snapshot 是不会修改服务端原始状态的设备数据副本。
    snapshot = dict(devices[role])
    # last_seen 是该设备最后一次成功上报的 Unix 时间戳。
    last_seen = snapshot.pop("last_seen_epoch")
    snapshot["last_seen"] = utc_label(last_seen)
    snapshot["age_seconds"] = None if last_seen is None else round(now - last_seen, 1)
    snapshot["online"] = last_seen is not None and now - last_seen <= ONLINE_WINDOW_SECONDS
    return snapshot


# slave_over_threshold 判断 A 从机的最新采样是否超过阈值。
def slave_over_threshold():
    # value 是 A 从机最后一个有效 ADC 原始值。
    value = devices["slave_a"]["adc_latest"]
    return isinstance(value, int) and value > THRESHOLD_RAW


# automatic_led 返回自动模式下四块设备共同采用的灯状态。
def automatic_led():
    return slave_over_threshold()


# cancel_timed_mode 清除当前临时模式倒计时，但不主动改变灯状态。
def cancel_timed_mode():
    timed_mode.update(id=None, name=None, deadline=None)


# update_timed_mode 在倒计时到期时恢复自动阈值检测。
def update_timed_mode(now):
    # deadline 是当前模式应当结束的 Unix 时间戳。
    deadline = timed_mode["deadline"]
    if deadline is None or now < deadline:
        return
    # finished_name 保存刚结束的模式名，供事件日志显示。
    finished_name = timed_mode["name"]
    control["threshold_enabled"] = True
    cancel_timed_mode()
    events.appendleft({"type": "timed_mode_finished", "name": finished_name,
                       "timestamp": utc_label(now)})


# parse_tf_modes 把主机发送的紧凑文本转换为网页可以直接使用的模式字典。
def parse_tf_modes(encoded_data):
    # parsed_modes 收集通过全部字段校验的模式。
    parsed_modes = {}
    for record in encoded_data.split(";"):
        # fields 依次对应编号、名称、秒数和四盏灯状态。
        fields = record.split("|")
        if len(fields) != 7:
            continue
        # mode_id 是只由字母、数字和下划线组成的内部编号。
        mode_id = fields[0]
        if not mode_id or len(mode_id) > 32 or not all(character.isalnum() or character == "_" for character in mode_id):
            continue
        try:
            # mode_name 是从百分号编码还原的网页显示名称。
            mode_name = unquote(fields[1], encoding="utf-8", errors="strict").strip()
        except (UnicodeError, ValueError):
            continue
        if not mode_name or len(mode_name) > MAX_MODE_NAME_LENGTH:
            continue
        if any(value not in ("0", "1") for value in fields[3:]):
            continue
        # led_states 把四个 0/1 字段转换为逻辑灯状态。
        led_states = {role: fields[index + 3] == "1" for index, role in enumerate(DEVICE_ROLES)}
        parsed_modes[mode_id] = {
            "id": mode_id, "name": mode_name,
            "led_states": led_states,
        }
    return parsed_modes


# encode_tf_mode 把一个网页模式转换为主机可以原样写入 TF 卡的单行记录。
def encode_tf_mode(mode):
    # states 是需要按固定设备顺序编码的四盏灯状态。
    states = mode["led_states"]
    # encoded_name 避免中文、竖线或引号破坏串口和 JSON 协议。
    encoded_name = quote(mode["name"], safe="", encoding="utf-8", errors="strict")
    # 第三个字段保留为 0，以便兼容已经部署的七字段 TF 文件格式；它不再代表固定时间。
    fields = [mode["id"], encoded_name, "0"]
    fields.extend("1" if states[role] else "0" for role in DEVICE_ROLES)
    return "|".join(fields)


# queue_tf_command 保存一条等待 COM10 主机执行的 TF 文件命令。
def queue_tf_command(operation, record):
    # command_id 是 1 到 65535 循环使用的幂等命令编号。
    command_id = tf_mode_state["next_command_id"]
    tf_mode_state["next_command_id"] = 1 if command_id >= 65535 else command_id + 1
    tf_mode_state["pending_command"] = {
        "id": command_id, "operation": operation, "record": record,
    }
    tf_mode_state["last_write_error"] = None
    return command_id


# active_lighting_preset 判断当前手动目标是否完整匹配某个组合模式。
def active_lighting_preset():
    if control["threshold_enabled"]:
        return None
    for mode_id, mode in tf_mode_state["modes"].items():
        if control["manual_led"] == mode["led_states"]:
            return mode_id
    return None


# apply_lighting_preset 关闭阈值检测，并一次性写入组合模式的四盏灯状态。
def apply_lighting_preset(preset_name, duration_seconds):
    # selected_mode 是 TF 卡中与网页选择对应的完整模式。
    selected_mode = tf_mode_state["modes"][preset_name]
    # led_states 是该模式中四块设备各自应采用的目标状态。
    led_states = selected_mode["led_states"]
    control["threshold_enabled"] = False
    control["manual_led"].update(led_states)
    timed_mode.update(id=preset_name, name=selected_mode["name"],
                      deadline=time() + duration_seconds)
    events.appendleft({"type": "preset", "preset": preset_name, "timestamp": utc_label(time())})


# device_config 生成指定设备下一次轮询需要执行的控制配置。
def device_config(role):
    # pending_command 是尚未被主机确认的 TF 卡写入命令。
    pending_command = tf_mode_state["pending_command"] if role == "master" else None
    return {
        "threshold_enabled": control["threshold_enabled"],
        "threshold_raw": THRESHOLD_RAW,
        "manual_led": control["manual_led"][role],
        "slave_over_threshold": slave_over_threshold(),
        "automatic_led": automatic_led(),
        "slave_adc_raw": devices["slave_a"]["adc_latest"] or 0,
        "slave_current_ma": devices["slave_a"]["current_ma"] or 0.0,
        "ina219_ready": devices["slave_a"]["ina219_ready"],
        "slave_a_led": devices["slave_a"]["led"] is True,
        "slave_b_led": devices["slave_b"]["led"] is True,
        "slave_c_led": devices["slave_c"]["led"] is True,
        "tf_command_id": pending_command["id"] if pending_command else 0,
        "tf_command_operation": pending_command["operation"] if pending_command else "",
        "tf_command_record": pending_command["record"] if pending_command else "",
    }


# 返回 AI 判断所需的当前模式、阈值结果和四块设备状态。
def assistant_state(now):
    # local_datetime 是带明确时区的当前本地日期时间。
    local_datetime = datetime.fromtimestamp(now, LOCAL_TIME_ZONE)
    return {
        "threshold_enabled": control["threshold_enabled"],
        "slave_over_threshold": slave_over_threshold(),
        "local_time": local_datetime.isoformat(timespec="seconds"),
        "threshold_voltage": THRESHOLD_VOLTAGE,
        "adc_voltage": round((devices["slave_a"]["adc_latest"] or 0) / ADC_MAX_VALUE * ADC_REFERENCE_VOLTAGE, 3),
        "tf_card_ready": tf_mode_state["card_ready"],
        "tf_modes": list(tf_mode_state["modes"].values()),
        "active_timed_mode": dict(timed_mode),
        "devices": {role: public_device(role, now) for role in DEVICE_ROLES},
    }


# apply_assistant_actions 执行已通过白名单校验的 AI 动作，并返回实际说明。
def apply_assistant_actions(actions):
    # proposed_threshold_enabled 先模拟整组动作，防止执行一半才发现冲突。
    proposed_threshold_enabled = control["threshold_enabled"]
    for action in actions:
        if action["type"] == "set_mode":
            proposed_threshold_enabled = action["mode"] == "automatic"
        elif action["type"] == "set_preset":
            if action["preset"] not in tf_mode_state["modes"]:
                raise AssistantError("这个 TF 模式刚刚发生了变化，请重新说一次。")
            proposed_threshold_enabled = False
        elif proposed_threshold_enabled:
            raise AssistantError("自动检测开启时不能单独控制 LED。")

    # executed 保存网页要显示的真实执行结果，不采用模型自报结果。
    executed = []
    for action in actions:
        if action["type"] == "set_mode":
            # enabled 将自然语言模式转换为原有阈值开关。
            enabled = action["mode"] == "automatic"
            control["threshold_enabled"] = enabled
            cancel_timed_mode()
            executed.append("已切换为自动检测" if enabled else "已切换为手动控制")
            events.appendleft({"type": "mode", "enabled": enabled, "timestamp": utc_label(time())})
            continue

        if action["type"] == "set_preset":
            # preset_name 是已经通过白名单校验的组合模式名称。
            preset_name = action["preset"]
            # duration_seconds 是本次执行使用的时间，不会写回 TF 卡模式。
            duration_seconds = action["duration_seconds"]
            apply_lighting_preset(preset_name, duration_seconds)
            # mode_name 是当前动态 TF 模式的用户可见名称。
            mode_name = tf_mode_state["modes"][preset_name]["name"]
            executed.append(f"{mode_name} 已启用，将运行 {duration_seconds} 秒")
            continue

        # role 是已经通过白名单校验的设备名称。
        role = action["role"]
        # led_on 是要写入该设备手动配置的逻辑灯状态。
        led_on = action["on"]
        cancel_timed_mode()
        control["manual_led"][role] = led_on
        # role_label 是适合网页显示的中文设备名。
        role_label = {"master": "主机", "slave_a": "A 从机", "slave_b": "B 从机", "slave_c": "C 从机"}[role]
        executed.append(f"{role_label} LED 已设为{'开' if led_on else '关'}")
    return executed


# allow_assistant_request 检查访问端是否超过 AI 请求额度，并记录本次请求。
def allow_assistant_request(remote_address, now):
    # request_times 保存当前访问端在限流窗口内的请求时间。
    request_times = assistant_requests.setdefault(remote_address, deque())
    while request_times and now - request_times[0] >= ASSISTANT_RATE_WINDOW_SECONDS:
        request_times.popleft()
    if len(request_times) >= ASSISTANT_RATE_LIMIT:
        return False
    request_times.append(now)
    return True


@app.get("/")
# index 返回控制台主页面。
def index():
    return render_template("index.html")


@app.get("/tokens.css")
# tokens 返回项目根目录中统一维护的设计令牌。
def tokens():
    return send_from_directory(PROJECT_ROOT, "tokens.css", mimetype="text/css")


@app.post("/api/device-status")
# update_device_status 接收 ESP8266 的状态和 ADC 批量上报。
def update_device_status():
    # payload 是设备通过 HTTP POST 发来的 JSON 数据。
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("role") not in DEVICE_ROLES:
        return jsonify(error="role must be master, slave_a, slave_b, or slave_c"), 400
    if not isinstance(payload.get("led"), bool):
        return jsonify(error="led must be a JSON boolean"), 400

    # role 是本次上报设备的身份。
    role = payload["role"]
    # samples 是 A 从机批量上传的 ADC 原始采样列表。
    samples = payload.get("adc_samples", [])
    # interval 是相邻采样之间的目标微秒数。
    interval = payload.get("sample_interval_us")
    # current_ma 是从机 A 的 INA219 实时电流，单位为毫安。
    current_ma = payload.get("current_ma")
    # ina219_ready 表示从机 A 是否已经找到传感器并读到有效值。
    ina219_ready = payload.get("ina219_ready", False)
    if role != "slave_a" and samples:
        return jsonify(error="only slave_a may send ADC samples"), 400
    if not isinstance(samples, list) or len(samples) > 600:
        return jsonify(error="adc_samples must contain at most 600 values"), 400
    if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= ADC_MAX_VALUE for value in samples):
        return jsonify(error="ADC values must be integers from 0 to 1023"), 400
    if samples and (not isinstance(interval, int) or not 500 <= interval <= 1000000):
        return jsonify(error="sample_interval_us must be from 500 to 1000000"), 400
    if current_ma is not None and (
        role != "slave_a" or isinstance(current_ma, bool)
        or not isinstance(current_ma, (int, float)) or not isfinite(current_ma)
        or not -5000.0 <= current_ma <= 5000.0
    ):
        return jsonify(error="current_ma must be a finite slave_a value from -5000 to 5000"), 400
    if not isinstance(ina219_ready, bool):
        return jsonify(error="ina219_ready must be a JSON boolean"), 400

    # now 是服务器收到本次上报的 Unix 时间戳。
    now = time()
    with state_lock:
        update_timed_mode(now)
        # previous_led 是本次上报前服务端保存的灯状态。
        previous_led = devices[role]["led"]
        devices[role].update(
            led=payload["led"], last_seen_epoch=now,
            device_ip=payload.get("ip") or request.remote_addr,
            rssi=payload.get("rssi"), uptime_ms=payload.get("uptime_ms"),
            adc_latest=samples[-1] if samples else devices[role]["adc_latest"],
            sample_interval_us=interval if samples else devices[role]["sample_interval_us"],
            current_ma=float(current_ma) if current_ma is not None else devices[role]["current_ma"],
            ina219_ready=ina219_ready if role == "slave_a" else False,
            alert=bool(payload.get("alert", False)),
        )
        for index, value in enumerate(samples):
            adc_waveform.append({
                "timestamp_ms": round(now * 1000 - (len(samples) - index - 1) * interval / 1000),
                "value": value,
            })
        if samples:
            adc_batches.append((now, len(samples)))
        if previous_led is not None and previous_led != payload["led"]:
            events.appendleft({"role": role, "led": payload["led"], "timestamp": utc_label(now)})
        if role == "master":
            # card_ready 是主机报告的 TF 模式文件可用状态。
            card_ready = payload.get("tf_card_ready")
            # encoded_modes 是主机从 TF 文件读取的全部紧凑模式。
            encoded_modes = payload.get("tf_modes_data")
            if isinstance(card_ready, bool):
                tf_mode_state["card_ready"] = card_ready
            if card_ready and isinstance(encoded_modes, str) and len(encoded_modes) <= 4096:
                # parsed_modes 是经过格式、长度和数值范围校验的卡内模式。
                parsed_modes = parse_tf_modes(encoded_modes)
                if parsed_modes:
                    tf_mode_state["modes"] = parsed_modes
            # acknowledged_id 是主机最近实际处理完成的写卡命令编号。
            acknowledged_id = payload.get("tf_command_ack")
            # command_succeeded 表示临时文件替换和重新读取是否全部成功。
            command_succeeded = payload.get("tf_command_success")
            # pending_command 是服务端当前等待主机确认的命令。
            pending_command = tf_mode_state["pending_command"]
            if pending_command and acknowledged_id == pending_command["id"]:
                tf_mode_state["last_write_error"] = None if command_succeeded else "TF 卡写入失败"
                tf_mode_state["pending_command"] = None
        response = device_config(role)
    return jsonify(ok=True, **response)


@app.get("/api/device-config/<role>")
# read_device_config 返回指定设备当前应执行的配置。
def read_device_config(role):
    if role not in DEVICE_ROLES:
        return jsonify(error="unknown device role"), 404
    with state_lock:
        update_timed_mode(time())
        response = device_config(role)
    return jsonify(response)


@app.post("/api/settings")
# update_settings 根据网页开关切换自动检测或手动模式。
def update_settings():
    # payload 是网页提交的模式设置 JSON。
    payload = request.get_json(silent=True) or {}
    # enabled 表示是否开启自动阈值检测。
    enabled = payload.get("threshold_enabled")
    if not isinstance(enabled, bool):
        return jsonify(error="threshold_enabled must be a JSON boolean"), 400
    with state_lock:
        control["threshold_enabled"] = enabled
        cancel_timed_mode()
        events.appendleft({"type": "mode", "enabled": enabled, "timestamp": utc_label(time())})
    return jsonify(ok=True, threshold_enabled=enabled)


@app.post("/api/lighting-preset/<preset_name>")
# set_lighting_preset 把网页选择的组合模式原子地写入四块设备目标状态。
def set_lighting_preset(preset_name):
    # 旧接口保留 10 秒兼容行为；新版网页使用可传时间的 activate 接口。
    with state_lock:
        if preset_name not in tf_mode_state["modes"]:
            return jsonify(error="unknown lighting preset"), 404
        apply_lighting_preset(preset_name, 10)
        # led_states 是返回网页核对的四块设备目标状态副本。
        led_states = dict(control["manual_led"])
    return jsonify(ok=True, preset=preset_name, threshold_enabled=False, led_states=led_states)


@app.post("/api/tf-modes")
# create_tf_mode 校验网页新模式，并排队交给 COM10 主机写入 TF 卡。
def create_tf_mode():
    # payload 是网页新建模式表单提交的 JSON。
    payload = request.get_json(silent=True) or {}
    # mode_name 是去掉首尾空格后的用户模式名称。
    mode_name = payload.get("name", "").strip() if isinstance(payload.get("name"), str) else ""
    # led_states 是网页提交的四盏灯逻辑状态。
    led_states = payload.get("led_states")
    if not mode_name or len(mode_name) > MAX_MODE_NAME_LENGTH:
        return jsonify(error=f"模式名称应为 1 至 {MAX_MODE_NAME_LENGTH} 个字符"), 400
    if not isinstance(led_states, dict) or set(led_states) != set(DEVICE_ROLES):
        return jsonify(error="必须设置主机和 A、B、C 从机状态"), 400
    if any(not isinstance(led_states[role], bool) for role in DEVICE_ROLES):
        return jsonify(error="LED 状态必须为开或关"), 400
    with state_lock:
        if not tf_mode_state["card_ready"]:
            return jsonify(error="主机 TF 卡当前不可用"), 409
        if tf_mode_state["pending_command"]:
            return jsonify(error="上一条 TF 卡命令仍在执行"), 409
        if len(tf_mode_state["modes"]) >= MAX_TF_MODES:
            return jsonify(error=f"TF 卡最多保存 {MAX_TF_MODES} 个模式"), 409
        if any(mode["name"] == mode_name for mode in tf_mode_state["modes"].values()):
            return jsonify(error="模式名称已存在"), 409
        # used_ids 是当前卡内所有模式编号，避免重启 Flask 后产生重复编号。
        used_ids = set(tf_mode_state["modes"])
        # custom_index 从 1 开始寻找第一个尚未使用的自定义编号。
        custom_index = 1
        while f"mode_custom_{custom_index}" in used_ids:
            custom_index += 1
        # new_mode 是等待持久化到 TF 卡的完整模式对象。
        new_mode = {
            "id": f"mode_custom_{custom_index}", "name": mode_name,
            "led_states": {role: led_states[role] for role in DEVICE_ROLES},
        }
        # command_id 是本次异步写卡操作的跟踪编号。
        command_id = queue_tf_command("add", encode_tf_mode(new_mode))
    return jsonify(ok=True, queued=True, command_id=command_id), 202


@app.post("/api/tf-modes/<mode_id>/activate")
# activate_tf_mode 立即执行卡内模式，并设置到期恢复自动检测的时间。
def activate_tf_mode(mode_id):
    # payload 保存用户为本次执行单独选择的持续时间。
    payload = request.get_json(silent=True) or {}
    # duration_seconds 不属于模式本身，每次点击执行都可以不同。
    duration_seconds = payload.get("duration_seconds")
    if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, int) or not 1 <= duration_seconds <= MAX_MODE_DURATION_SECONDS:
        return jsonify(error=f"本次时间应为 1 至 {MAX_MODE_DURATION_SECONDS} 秒"), 400
    with state_lock:
        update_timed_mode(time())
        if mode_id not in tf_mode_state["modes"]:
            return jsonify(error="模式不存在或尚未同步"), 404
        apply_lighting_preset(mode_id, duration_seconds)
        # selected_mode 是刚刚开始执行的模式，用于构造网页确认信息。
        selected_mode = tf_mode_state["modes"][mode_id]
    return jsonify(ok=True, mode=selected_mode, duration_seconds=duration_seconds,
                   threshold_enabled=False)


@app.post("/api/tf-modes/<mode_id>/delete")
# delete_tf_mode 把自定义模式的删除操作排队交给 COM10 主机。
def delete_tf_mode(mode_id):
    if mode_id in DEFAULT_TF_MODES:
        return jsonify(error="内置模式不能删除"), 409
    with state_lock:
        if mode_id not in tf_mode_state["modes"]:
            return jsonify(error="模式不存在"), 404
        if not tf_mode_state["card_ready"]:
            return jsonify(error="主机 TF 卡当前不可用"), 409
        if tf_mode_state["pending_command"]:
            return jsonify(error="上一条 TF 卡命令仍在执行"), 409
        if timed_mode["id"] == mode_id:
            control["threshold_enabled"] = True
            cancel_timed_mode()
        # command_id 是本次异步删除操作的跟踪编号。
        command_id = queue_tf_command("delete", mode_id)
    return jsonify(ok=True, queued=True, command_id=command_id), 202


@app.post("/api/device-command/<role>")
# set_device_led 保存网页为指定设备设置的手动 LED 目标。
def set_device_led(role):
    if role not in DEVICE_ROLES:
        return jsonify(error="unknown device role"), 404
    # payload 是网页提交的 LED 命令 JSON。
    payload = request.get_json(silent=True) or {}
    # led 是用户要求的逻辑灯状态，true 表示点亮。
    led = payload.get("led")
    if not isinstance(led, bool):
        return jsonify(error="led must be a JSON boolean"), 400
    with state_lock:
        if control["threshold_enabled"]:
            return jsonify(error="disable threshold detection before manual control"), 409
        cancel_timed_mode()
        control["manual_led"][role] = led
    return jsonify(ok=True, role=role, led=led)


@app.post("/api/assistant-command")
# assistant_command 处理聊天、时间、天气和设备控制四类自然语言请求。
def assistant_command():
    # payload 是网页发送的单轮对话 JSON。
    payload = request.get_json(silent=True) or {}
    # message 是用户在网页文本框中输入的自然语言内容。
    message = payload.get("message")
    # history 是浏览器保存的最近几轮对话，用于理解连续追问。
    history = payload.get("history", [])
    if not isinstance(message, str):
        return jsonify(error="message must be a string"), 400

    try:
        with state_lock:
            if not allow_assistant_request(request.remote_addr or "unknown", time()):
                return jsonify(error="请求过于频繁，请稍后再试。"), 429
            # state_snapshot 固定模型判断时看到的设备状态。
            state_snapshot = assistant_state(time())
        # plan 是 DeepSeek 生成但尚未执行的候选计划。
        plan = request_control_plan(message, state_snapshot, history)
        # validated_plan 包含经过本地白名单校验的意图、回复和动作。
        # allowed_presets 来自主机刚同步的 TF 卡，包含用户新建模式而非固定白名单。
        allowed_presets = {mode["id"] for mode in state_snapshot["tf_modes"]}
        validated_plan = validate_control_plan(plan, allowed_presets)
        # reply 是准备返回网页的自然语言回复。
        reply = validated_plan["reply"]
        # weather_data 保存实时天气源返回的可信观测；非天气请求保持为空。
        weather_data = None
        if validated_plan["intent"] == "weather" and validated_plan["weather_city"]:
            try:
                weather_data = get_current_weather(validated_plan["weather_city"])
                reply = request_weather_reply(message, weather_data)
            except WeatherError as error:
                reply = f"我听懂了天气问题，但{str(error)}"
        with state_lock:
            # executed 记录后端实际写入的模式和 LED 配置。
            executed = apply_assistant_actions(validated_plan["actions"])
        return jsonify(
            ok=True,
            intent=validated_plan["intent"],
            reply=reply,
            executed=executed,
            weather=weather_data,
        )
    except AssistantError as error:
        return jsonify(error=str(error)), 502


@app.get("/api/dashboard")
# read_dashboard 汇总设备状态、告警与经过抽取的波形数据。
def read_dashboard():
    # now 是生成本次仪表盘快照的 Unix 时间戳。
    now = time()
    with state_lock:
        update_timed_mode(now)
        # snapshots 保存四块设备对网页可见的状态副本。
        snapshots = {role: public_device(role, now) for role in DEVICE_ROLES}
        # points 是当前保留的全部 ADC 波形点副本。
        points = list(adc_waveform)
        # event_snapshot 是最近状态事件的副本。
        event_snapshot = list(events)
        # batch_snapshot 是近期 ADC 批次统计的副本。
        batch_snapshot = list(adc_batches)
        # enabled 表示当前是否处于自动阈值检测模式。
        enabled = control["threshold_enabled"]
        # active_preset 是当前手动目标恰好匹配的组合模式。
        active_preset = active_lighting_preset()
        # over_threshold 表示 A 从机最新数据是否超过阈值。
        over_threshold = slave_over_threshold()
        # mode_snapshot 是 TF 卡同步模式的网页安全副本。
        mode_snapshot = list(tf_mode_state["modes"].values())
        # timed_mode_snapshot 固定本次响应中的倒计时信息。
        timed_mode_snapshot = dict(timed_mode)
        # tf_pending 表示网页操作是否还在等待主机真实写入 TF 卡。
        tf_pending = tf_mode_state["pending_command"] is not None
        # tf_error 是最近一次主机写卡失败时返回的简短原因。
        tf_error = tf_mode_state["last_write_error"]

    if points:
        cutoff_ms = points[-1]["timestamp_ms"] - 15000
        points = [point for point in points if point["timestamp_ms"] >= cutoff_ms]
    # captured_points 是最近 15 秒实际收到的原始点数。
    captured_points = len(points)
    # values 只提取 ADC 数值，供最小值和最大值统计使用。
    values = [point["value"] for point in points]
    if len(points) > WAVEFORM_DISPLAY_POINTS:
        # step 是网页绘图抽取原始点时采用的步长。
        step = max(1, len(points) // WAVEFORM_DISPLAY_POINTS)
        points = points[::step]
    # latest 是 A 从机最新 ADC 原始值。
    latest = snapshots["slave_a"]["adc_latest"]
    # recent_batches 只保留最近五秒收到的采样批次。
    recent_batches = [batch for batch in batch_snapshot if batch[0] >= now - 5]
    # effective_rate 是根据服务端实收点数估算的采样率。
    effective_rate = None
    if recent_batches:
        # measured_seconds 是参与估算的采样时间跨度。
        measured_seconds = max(0.5, now - recent_batches[0][0])
        effective_rate = round(sum(batch[1] for batch in recent_batches) / measured_seconds)
    return jsonify(
        devices=snapshots, threshold_enabled=enabled, active_lighting_preset=active_preset,
        threshold_voltage=THRESHOLD_VOLTAGE, threshold_raw=THRESHOLD_RAW,
        slave_over_threshold=over_threshold,
        alert_message="电压大于阈值" if snapshots["master"]["alert"] else None,
        adc_voltage=round(latest / ADC_MAX_VALUE * ADC_REFERENCE_VOLTAGE, 3) if isinstance(latest, int) else None,
        adc_min=min(values) if values else None, adc_max=max(values) if values else None,
        sample_rate_hz=round(1000000 / snapshots["slave_a"]["sample_interval_us"]) if snapshots["slave_a"]["sample_interval_us"] else None,
        effective_sample_rate_hz=effective_rate,
        captured_points=captured_points, waveform=points, events=event_snapshot,
        tf_card_ready=tf_mode_state["card_ready"], tf_modes=mode_snapshot,
        tf_command_pending=tf_pending, tf_write_error=tf_error,
        active_timed_mode={
            "id": timed_mode_snapshot["id"], "name": timed_mode_snapshot["name"],
            "remaining_seconds": max(0, int(timed_mode_snapshot["deadline"] - now + 0.999))
            if timed_mode_snapshot["deadline"] is not None else None,
        },
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
