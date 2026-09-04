const elements = {
  networkState: document.querySelector("#networkState"),
  thresholdEnabled: document.querySelector("#thresholdEnabled"),
  modeLabel: document.querySelector("#modeLabel"),
  alertBand: document.querySelector("#alertBand"),
  commandStatus: document.querySelector("#commandStatus"),
  manualButtons: document.querySelectorAll("[data-role][data-led]"),
  adcChart: document.querySelector("#adcChart"),
};

let waveform = [];
let thresholdRaw = 614;

const setText = (id, value) => {
  document.querySelector(`#${id}`).textContent = value ?? "—";
};

const renderDevice = (role, device) => {
  setText(`${role}Online`, device.online ? "在线" : "离线");
  setText(`${role}Led`, device.led === null ? "等待上报" : device.led ? "亮" : "灭");
  setText(`${role}Ip`, device.device_ip);
  document.querySelector(`[data-device="${role}"]`).dataset.online = String(device.online);
  document.querySelector(`#${role}Lamp`).dataset.on = String(device.led === true);
};

const cssColor = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const drawWaveform = () => {
  const canvas = elements.adcChart;
  const bounds = canvas.getBoundingClientRect();
  const scale = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.max(1, Math.round(bounds.width));
  const height = Math.max(1, Math.round(bounds.height));
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const context = canvas.getContext("2d");
  context.scale(scale, scale);
  context.clearRect(0, 0, width, height);
  const pad = { top: 18, right: 14, bottom: 28, left: 44 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  context.font = `11px ${cssColor("--font-mono")}`;
  context.strokeStyle = cssColor("--color-rule");
  context.fillStyle = cssColor("--color-muted");
  context.textAlign = "right";
  [0, 256, 512, 768, 1023].forEach((value) => {
    const y = pad.top + plotHeight - (value / 1023) * plotHeight;
    context.beginPath(); context.moveTo(pad.left, y); context.lineTo(width - pad.right, y); context.stroke();
    if ([0, 512, 1023].includes(value)) context.fillText(String(value), pad.left - 7, y + 4);
  });
  const thresholdY = pad.top + plotHeight - (thresholdRaw / 1023) * plotHeight;
  context.setLineDash([6, 5]);
  context.strokeStyle = cssColor("--color-warning");
  context.beginPath(); context.moveTo(pad.left, thresholdY); context.lineTo(width - pad.right, thresholdY); context.stroke();
  context.setLineDash([]);
  if (!waveform.length) return;
  const end = waveform.at(-1).timestamp_ms;
  const start = end - 15000;
  const visible = waveform.filter((point) => point.timestamp_ms >= start);
  context.strokeStyle = cssColor("--color-accent");
  context.lineWidth = 2;
  context.beginPath();
  visible.forEach((point, index) => {
    const x = pad.left + ((point.timestamp_ms - start) / 15000) * plotWidth;
    const y = pad.top + plotHeight - (point.value / 1023) * plotHeight;
    index ? context.lineTo(x, y) : context.moveTo(x, y);
  });
  context.stroke();
};

const render = (status) => {
  const { master, slave } = status.devices;
  renderDevice("master", master);
  renderDevice("slave", slave);
  elements.networkState.dataset.online = String(master.online && slave.online);
  elements.networkState.lastElementChild.textContent = master.online && slave.online ? "两台设备在线" : "设备未全部在线";
  elements.thresholdEnabled.checked = status.threshold_enabled;
  elements.modeLabel.textContent = status.threshold_enabled ? "自动检测" : "手动控制";
  elements.manualButtons.forEach((button) => (button.disabled = status.threshold_enabled));
  elements.alertBand.hidden = !status.alert_message;
  setText("adcVoltage", Number.isFinite(status.adc_voltage) ? `${status.adc_voltage.toFixed(3)} V` : null);
  setText("adcRaw", slave.adc_latest);
  setText("thresholdResult", status.slave_over_threshold ? "超过 0.600 V" : "未超过阈值");
  setText("masterAlert", status.alert_message || "无告警");
  setText("sampleRate", Number.isFinite(status.effective_sample_rate_hz) ? `${status.effective_sample_rate_hz} Hz（目标 ${status.sample_rate_hz}）` : null);
  setText("adcRange", Number.isFinite(status.adc_min) ? `${status.adc_min}–${status.adc_max}` : null);
  waveform = status.waveform || [];
  thresholdRaw = status.threshold_raw;
  drawWaveform();
};

const requestJson = async (url, body) => {
  const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
};

const poll = async () => {
  try {
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch {
    elements.networkState.dataset.online = "false";
    elements.networkState.lastElementChild.textContent = "网站连接中断";
  }
};

elements.thresholdEnabled.addEventListener("change", async () => {
  elements.thresholdEnabled.disabled = true;
  try {
    await requestJson("/api/settings", { threshold_enabled: elements.thresholdEnabled.checked });
    elements.commandStatus.textContent = elements.thresholdEnabled.checked ? "已开启阈值检测" : "已进入手动控制";
    await poll();
  } catch {
    elements.commandStatus.textContent = "模式切换失败";
  } finally {
    elements.thresholdEnabled.disabled = false;
  }
});

elements.manualButtons.forEach((button) => button.addEventListener("click", async () => {
  elements.manualButtons.forEach((item) => (item.disabled = true));
  try {
    await requestJson(`/api/device-command/${button.dataset.role}`, { led: button.dataset.led === "true" });
    elements.commandStatus.textContent = "指令已发送，等待设备执行";
  } catch {
    elements.commandStatus.textContent = "指令发送失败，请确认已关闭阈值检测";
  }
  await poll();
}));

poll();
setInterval(poll, 500);
new ResizeObserver(drawWaveform).observe(elements.adcChart);
