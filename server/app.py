from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from time import time

from flask import Flask, jsonify, render_template, request, send_from_directory

try:
    # 直接运行 app.py 时使用同目录导入。
    from deepseek_assistant import AssistantError, request_control_plan, validate_control_plan
except ImportError:
    # 作为 server.app 导入测试时使用包内相对导入。
    from .deepseek_assistant import AssistantError, request_control_plan, validate_control_plan


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ONLINE_WINDOW_SECONDS = 4
ADC_MAX_VALUE = 1023
ADC_REFERENCE_VOLTAGE = 1.0
THRESHOLD_VOLTAGE = 0.6
THRESHOLD_RAW = round(THRESHOLD_VOLTAGE / ADC_REFERENCE_VOLTAGE * ADC_MAX_VALUE)
ADC_HISTORY_POINTS = 20000
WAVEFORM_DISPLAY_POINTS = 2000
DEVICE_ROLES = ("master", "slave_a", "slave_b", "slave_c")
# 单个访问端在 60 秒内最多发起 10 次 AI 请求。
ASSISTANT_RATE_LIMIT = 10
# AI 请求限流窗口长度，单位为秒。
ASSISTANT_RATE_WINDOW_SECONDS = 60

app = Flask(__name__)
state_lock = Lock()
devices = {
    role: {
        "led": None, "last_seen_epoch": None, "device_ip": None,
        "rssi": None, "uptime_ms": None, "adc_latest": None,
        "sample_interval_us": None, "alert": False,
    }
    for role in DEVICE_ROLES
}
control = {"threshold_enabled": True, "manual_led": {role: False for role in DEVICE_ROLES}}
adc_waveform = deque(maxlen=ADC_HISTORY_POINTS)
adc_batches = deque(maxlen=30)
events = deque(maxlen=20)
# assistant_requests 按访问端 IP 保存最近的 AI 请求时间。
assistant_requests = {}


def utc_label(epoch_seconds):
    if epoch_seconds is None:
        return None
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).isoformat()


def public_device(role, now):
    snapshot = dict(devices[role])
    last_seen = snapshot.pop("last_seen_epoch")
    snapshot["last_seen"] = utc_label(last_seen)
    snapshot["age_seconds"] = None if last_seen is None else round(now - last_seen, 1)
    snapshot["online"] = last_seen is not None and now - last_seen <= ONLINE_WINDOW_SECONDS
    return snapshot


def slave_over_threshold():
    value = devices["slave_a"]["adc_latest"]
    return isinstance(value, int) and value > THRESHOLD_RAW


def automatic_led():
    return slave_over_threshold()


def device_config(role):
    return {
        "threshold_enabled": control["threshold_enabled"],
        "threshold_raw": THRESHOLD_RAW,
        "manual_led": control["manual_led"][role],
        "slave_over_threshold": slave_over_threshold(),
        "automatic_led": automatic_led(),
        "slave_adc_raw": devices["slave_a"]["adc_latest"] or 0,
        "slave_a_led": devices["slave_a"]["led"] is True,
        "slave_b_led": devices["slave_b"]["led"] is True,
        "slave_c_led": devices["slave_c"]["led"] is True,
    }


# 返回 AI 判断所需的当前模式、阈值结果和四块设备状态。
def assistant_state(now):
    return {
        "threshold_enabled": control["threshold_enabled"],
        "slave_over_threshold": slave_over_threshold(),
        "devices": {role: public_device(role, now) for role in DEVICE_ROLES},
    }


# 依次执行已通过白名单校验的 AI 动作，并返回实际执行说明。
def apply_assistant_actions(actions):
    # proposed_threshold_enabled 先模拟整组动作，防止执行一半才发现冲突。
    proposed_threshold_enabled = control["threshold_enabled"]
    for action in actions:
        if action["type"] == "set_mode":
            proposed_threshold_enabled = action["mode"] == "automatic"
        elif proposed_threshold_enabled:
            raise AssistantError("自动检测开启时不能单独控制 LED。")

    # executed 保存网页要显示的真实执行结果，不采用模型自报结果。
    executed = []
    for action in actions:
        if action["type"] == "set_mode":
            # enabled 将自然语言模式转换为原有阈值开关。
            enabled = action["mode"] == "automatic"
            control["threshold_enabled"] = enabled
            executed.append("已切换为自动检测" if enabled else "已切换为手动控制")
            events.appendleft({"type": "mode", "enabled": enabled, "timestamp": utc_label(time())})
            continue

        # role 是已经通过白名单校验的设备名称。
        role = action["role"]
        # led_on 是要写入该设备手动配置的逻辑灯状态。
        led_on = action["on"]
        control["manual_led"][role] = led_on
        # role_label 是适合网页显示的中文设备名。
        role_label = {"master": "主机", "slave_a": "A 从机", "slave_b": "B 从机", "slave_c": "C 从机"}[role]
        executed.append(f"{role_label} LED 已设为{'开' if led_on else '关'}")
    return executed


# 检查访问端是否超过 AI 请求额度，并记录本次请求。
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
def index():
    return render_template("index.html")


@app.get("/tokens.css")
def tokens():
    return send_from_directory(PROJECT_ROOT, "tokens.css", mimetype="text/css")


@app.post("/api/device-status")
def update_device_status():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("role") not in DEVICE_ROLES:
        return jsonify(error="role must be master, slave_a, slave_b, or slave_c"), 400
    if not isinstance(payload.get("led"), bool):
        return jsonify(error="led must be a JSON boolean"), 400

    role = payload["role"]
    samples = payload.get("adc_samples", [])
    interval = payload.get("sample_interval_us")
    if role != "slave_a" and samples:
        return jsonify(error="only slave_a may send ADC samples"), 400
    if not isinstance(samples, list) or len(samples) > 600:
        return jsonify(error="adc_samples must contain at most 600 values"), 400
    if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= ADC_MAX_VALUE for value in samples):
        return jsonify(error="ADC values must be integers from 0 to 1023"), 400
    if samples and (not isinstance(interval, int) or not 500 <= interval <= 1000000):
        return jsonify(error="sample_interval_us must be from 500 to 1000000"), 400

    now = time()
    with state_lock:
        previous_led = devices[role]["led"]
        devices[role].update(
            led=payload["led"], last_seen_epoch=now,
            device_ip=payload.get("ip") or request.remote_addr,
            rssi=payload.get("rssi"), uptime_ms=payload.get("uptime_ms"),
            adc_latest=samples[-1] if samples else devices[role]["adc_latest"],
            sample_interval_us=interval if samples else devices[role]["sample_interval_us"],
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
        response = device_config(role)
    return jsonify(ok=True, **response)


@app.get("/api/device-config/<role>")
def read_device_config(role):
    if role not in DEVICE_ROLES:
        return jsonify(error="unknown device role"), 404
    with state_lock:
        response = device_config(role)
    return jsonify(response)


@app.post("/api/settings")
def update_settings():
    payload = request.get_json(silent=True) or {}
    enabled = payload.get("threshold_enabled")
    if not isinstance(enabled, bool):
        return jsonify(error="threshold_enabled must be a JSON boolean"), 400
    with state_lock:
        control["threshold_enabled"] = enabled
        events.appendleft({"type": "mode", "enabled": enabled, "timestamp": utc_label(time())})
    return jsonify(ok=True, threshold_enabled=enabled)


@app.post("/api/device-command/<role>")
def set_device_led(role):
    if role not in DEVICE_ROLES:
        return jsonify(error="unknown device role"), 404
    payload = request.get_json(silent=True) or {}
    led = payload.get("led")
    if not isinstance(led, bool):
        return jsonify(error="led must be a JSON boolean"), 400
    with state_lock:
        if control["threshold_enabled"]:
            return jsonify(error="disable threshold detection before manual control"), 409
        control["manual_led"][role] = led
    return jsonify(ok=True, role=role, led=led)


@app.post("/api/assistant-command")
def assistant_command():
    # payload 是网页发送的单轮对话 JSON。
    payload = request.get_json(silent=True) or {}
    # message 是用户输入或语音识别得到的自然语言指令。
    message = payload.get("message")
    if not isinstance(message, str):
        return jsonify(error="message must be a string"), 400

    try:
        with state_lock:
            if not allow_assistant_request(request.remote_addr or "unknown", time()):
                return jsonify(error="请求过于频繁，请稍后再试。"), 429
            # state_snapshot 固定模型判断时看到的设备状态。
            state_snapshot = assistant_state(time())
        # plan 是 DeepSeek 生成但尚未执行的候选计划。
        plan = request_control_plan(message, state_snapshot)
        # reply 和 actions 经过本地白名单校验后才可使用。
        reply, actions = validate_control_plan(plan)
        with state_lock:
            # executed 记录后端实际写入的模式和 LED 配置。
            executed = apply_assistant_actions(actions)
        return jsonify(ok=True, reply=reply, executed=executed)
    except AssistantError as error:
        return jsonify(error=str(error)), 502


@app.get("/api/dashboard")
def read_dashboard():
    now = time()
    with state_lock:
        snapshots = {role: public_device(role, now) for role in DEVICE_ROLES}
        points = list(adc_waveform)
        event_snapshot = list(events)
        batch_snapshot = list(adc_batches)
        enabled = control["threshold_enabled"]
        over_threshold = slave_over_threshold()

    if points:
        cutoff_ms = points[-1]["timestamp_ms"] - 15000
        points = [point for point in points if point["timestamp_ms"] >= cutoff_ms]
    captured_points = len(points)
    values = [point["value"] for point in points]
    if len(points) > WAVEFORM_DISPLAY_POINTS:
        step = max(1, len(points) // WAVEFORM_DISPLAY_POINTS)
        points = points[::step]
    latest = snapshots["slave_a"]["adc_latest"]
    recent_batches = [batch for batch in batch_snapshot if batch[0] >= now - 5]
    effective_rate = None
    if recent_batches:
        measured_seconds = max(0.5, now - recent_batches[0][0])
        effective_rate = round(sum(batch[1] for batch in recent_batches) / measured_seconds)
    return jsonify(
        devices=snapshots, threshold_enabled=enabled,
        threshold_voltage=THRESHOLD_VOLTAGE, threshold_raw=THRESHOLD_RAW,
        slave_over_threshold=over_threshold,
        alert_message="电压大于阈值" if snapshots["master"]["alert"] else None,
        adc_voltage=round(latest / ADC_MAX_VALUE * ADC_REFERENCE_VOLTAGE, 3) if isinstance(latest, int) else None,
        adc_min=min(values) if values else None, adc_max=max(values) if values else None,
        sample_rate_hz=round(1000000 / snapshots["slave_a"]["sample_interval_us"]) if snapshots["slave_a"]["sample_interval_us"] else None,
        effective_sample_rate_hz=effective_rate,
        captured_points=captured_points, waveform=points, events=event_snapshot,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
