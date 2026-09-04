from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from time import time

from flask import Flask, jsonify, render_template, request, send_from_directory


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ONLINE_WINDOW_SECONDS = 4
ADC_MAX_VALUE = 1023
ADC_HISTORY_POINTS = 4000

app = Flask(__name__)
state_lock = Lock()
device_state = {
    "led": None,
    "gpio": 4,
    "last_seen_epoch": None,
    "device_ip": None,
    "rssi": None,
    "uptime_ms": None,
    "adc_latest": None,
    "sample_interval_ms": None,
}
pending_command = None
next_command_id = 1
history = deque(maxlen=12)
adc_waveform = deque(maxlen=ADC_HISTORY_POINTS)


def utc_label(epoch_seconds):
    if epoch_seconds is None:
        return None
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).isoformat()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/tokens.css")
def tokens():
    return send_from_directory(PROJECT_ROOT, "tokens.css", mimetype="text/css")


@app.post("/api/status")
def update_status():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("led"), bool):
        return jsonify(error="led must be a JSON boolean"), 400

    samples = payload.get("adc_samples", [])
    sample_interval_ms = payload.get("sample_interval_ms")
    if not isinstance(samples, list) or len(samples) > 160:
        return jsonify(error="adc_samples must be a list with at most 160 values"), 400
    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= ADC_MAX_VALUE
        for value in samples
    ):
        return jsonify(error="ADC values must be integers from 0 to 1023"), 400
    if samples and (
        not isinstance(sample_interval_ms, int)
        or not 4 <= sample_interval_ms <= 1000
    ):
        return jsonify(error="sample_interval_ms must be from 4 to 1000"), 400

    now = time()
    global pending_command
    with state_lock:
        previous_led = device_state["led"]
        device_state.update(
            led=payload["led"],
            gpio=payload.get("gpio", 4),
            last_seen_epoch=now,
            device_ip=payload.get("ip") or request.remote_addr,
            rssi=payload.get("rssi"),
            uptime_ms=payload.get("uptime_ms"),
            adc_latest=samples[-1] if samples else device_state["adc_latest"],
            sample_interval_ms=(
                sample_interval_ms
                if samples
                else device_state["sample_interval_ms"]
            ),
        )
        if pending_command and pending_command["led"] == payload["led"]:
            pending_command = None
        for index, value in enumerate(samples):
            offset_ms = (len(samples) - index - 1) * sample_interval_ms
            adc_waveform.append(
                {
                    "timestamp_ms": round(now * 1000 - offset_ms),
                    "value": value,
                }
            )
        if previous_led is None or previous_led != payload["led"]:
            history.appendleft(
                {
                    "led": payload["led"],
                    "timestamp": utc_label(now),
                }
            )

    return jsonify(ok=True)


@app.get("/api/command")
def read_command():
    with state_lock:
        command = dict(pending_command) if pending_command else None
    return jsonify(command or {})


@app.post("/api/command")
def set_command():
    global pending_command, next_command_id
    payload = request.get_json(silent=True) or {}
    action = payload.get("action")
    with state_lock:
        current = device_state["led"]
        if action == "on":
            target = True
        elif action == "off":
            target = False
        elif action == "toggle" and isinstance(current, bool):
            target = not current
        else:
            return jsonify(error="action must be on, off, or toggle; device must be online for toggle"), 400
        pending_command = {"id": next_command_id, "led": target}
        next_command_id += 1
    return jsonify(ok=True, command=pending_command)


@app.get("/api/status")
def read_status():
    now = time()
    with state_lock:
        snapshot = dict(device_state)
        snapshot["history"] = list(history)
        points = list(adc_waveform)

    if points:
        cutoff_ms = points[-1]["timestamp_ms"] - 15000
        points = [point for point in points if point["timestamp_ms"] >= cutoff_ms]
    snapshot["waveform"] = points

    last_seen = snapshot.pop("last_seen_epoch")
    snapshot["last_seen"] = utc_label(last_seen)
    snapshot["age_seconds"] = None if last_seen is None else round(now - last_seen, 1)
    snapshot["online"] = (
        last_seen is not None and now - last_seen <= ONLINE_WINDOW_SECONDS
    )
    values = [point["value"] for point in snapshot["waveform"]]
    snapshot["adc_min"] = min(values) if values else None
    snapshot["adc_max"] = max(values) if values else None
    snapshot["sample_rate_hz"] = (
        round(1000 / snapshot["sample_interval_ms"])
        if snapshot["sample_interval_ms"]
        else None
    )
    return jsonify(snapshot)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
