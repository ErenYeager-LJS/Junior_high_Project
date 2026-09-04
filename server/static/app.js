const elements = {
  connectionText: document.querySelector("#connectionText"),
  ledState: document.querySelector("#ledState"),
  deviceIp: document.querySelector("#deviceIp"),
  rssi: document.querySelector("#rssi"),
  uptime: document.querySelector("#uptime"),
  lastSeen: document.querySelector("#lastSeen"),
  adcChart: document.querySelector("#adcChart"),
  adcCurrent: document.querySelector("#adcCurrent"),
  adcMin: document.querySelector("#adcMin"),
  adcMax: document.querySelector("#adcMax"),
  sampleRate: document.querySelector("#sampleRate"),
  commandStatus: document.querySelector("#commandStatus"),
  commandButtons: document.querySelectorAll("[data-led-action]"),
  events: document.querySelector("#events"),
};

let waveform = [];

const formatUptime = (milliseconds) => {
  if (!Number.isFinite(milliseconds)) return "—";
  const seconds = Math.floor(milliseconds / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return `${hours.toString().padStart(2, "0")}:${minutes
    .toString()
    .padStart(2, "0")}:${remainder.toString().padStart(2, "0")}`;
};

const formatTime = (isoTime) => {
  if (!isoTime) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(isoTime));
};

const renderHistory = (history) => {
  if (!history.length) {
    elements.events.innerHTML =
      '<li class="events__empty">设备连接后，变化会显示在这里。</li>';
    return;
  }

  elements.events.replaceChildren(
    ...history.map((event) => {
      const item = document.createElement("li");
      item.className = "event";
      item.dataset.led = event.led ? "on" : "off";

      const mark = document.createElement("span");
      mark.className = "event__mark";
      mark.setAttribute("aria-hidden", "true");

      const state = document.createElement("span");
      state.textContent = event.led ? "GPIO4 高电平" : "GPIO4 低电平";

      const time = document.createElement("time");
      time.className = "event__time";
      time.dateTime = event.timestamp;
      time.textContent = formatTime(event.timestamp);

      item.append(mark, state, time);
      return item;
    }),
  );
};

const cssColor = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

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

  const padding = { top: 16, right: 12, bottom: 26, left: 42 };
  const plotWidth = Math.max(1, width - padding.left - padding.right);
  const plotHeight = Math.max(1, height - padding.top - padding.bottom);
  const gridColor = cssColor("--color-rule");
  const labelColor = cssColor("--color-muted");

  context.font = `11px ${cssColor("--font-mono")}`;
  context.fillStyle = labelColor;
  context.strokeStyle = gridColor;
  context.lineWidth = 1;
  context.textAlign = "right";
  context.textBaseline = "middle";

  [0, 256, 512, 768, 1023].forEach((value) => {
    const y = padding.top + plotHeight - (value / 1023) * plotHeight;
    context.beginPath();
    context.moveTo(padding.left, y);
    context.lineTo(width - padding.right, y);
    context.stroke();
    if (value === 0 || value === 512 || value === 1023) {
      context.fillText(String(value), padding.left - 7, y);
    }
  });

  context.textBaseline = "bottom";
  context.textAlign = "left";
  context.fillText("-15 s", padding.left, height - 2);
  context.textAlign = "right";
  context.fillText("0 s", width - padding.right, height - 2);

  if (waveform.length === 0) {
    return;
  }

  const endTime = waveform[waveform.length - 1].timestamp_ms;
  const startTime = endTime - 15000;
  const visible = waveform.filter((point) => point.timestamp_ms >= startTime);
  context.strokeStyle = cssColor("--color-led-on");
  context.lineWidth = 2;
  context.lineJoin = "round";
  context.lineCap = "round";
  context.beginPath();
  visible.forEach((point, index) => {
    const x =
      padding.left + ((point.timestamp_ms - startTime) / 15000) * plotWidth;
    const y = padding.top + plotHeight - (point.value / 1023) * plotHeight;
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
  context.stroke();

  const latest = visible[visible.length - 1];
  const latestX =
    padding.left + ((latest.timestamp_ms - startTime) / 15000) * plotWidth;
  const latestY =
    padding.top + plotHeight - (latest.value / 1023) * plotHeight;
  context.fillStyle = cssColor("--color-led-on");
  context.beginPath();
  context.arc(latestX, latestY, 3.5, 0, Math.PI * 2);
  context.fill();
};

const renderWaveform = (status) => {
  waveform = status.waveform || [];
  elements.adcCurrent.textContent = Number.isFinite(status.adc_latest)
    ? status.adc_latest
    : "—";
  elements.adcMin.textContent = Number.isFinite(status.adc_min)
    ? status.adc_min
    : "—";
  elements.adcMax.textContent = Number.isFinite(status.adc_max)
    ? status.adc_max
    : "—";
  elements.sampleRate.textContent = Number.isFinite(status.sample_rate_hz)
    ? `${status.sample_rate_hz} Hz`
    : "—";
  elements.adcChart.setAttribute(
    "aria-label",
    Number.isFinite(status.adc_latest)
      ? `A0 当前采样值 ${status.adc_latest}`
      : "等待 A0 采样数据",
  );
  drawWaveform();
};

const render = (status) => {
  document.body.dataset.online = String(status.online);
  document.body.dataset.led = status.led === null ? "unknown" : status.led ? "on" : "off";

  elements.connectionText.textContent = status.online ? "设备在线" : "设备离线";
  elements.ledState.textContent =
    status.led === null ? "等待上报" : status.led ? "高电平 / ON" : "低电平 / OFF";
  elements.deviceIp.textContent = status.device_ip || "—";
  elements.rssi.textContent = Number.isFinite(status.rssi) ? `${status.rssi} dBm` : "—";
  elements.uptime.textContent = formatUptime(status.uptime_ms);
  elements.lastSeen.textContent = status.last_seen ? `${formatTime(status.last_seen)} · ${status.age_seconds} 秒前` : "—";
  renderWaveform(status);
  renderHistory(status.history || []);
};

const poll = async () => {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch {
    document.body.dataset.online = "false";
    elements.connectionText.textContent = "网站连接中断";
  }
};

const sendLedCommand = async (action) => {
  elements.commandButtons.forEach((button) => (button.disabled = true));
  elements.commandStatus.textContent = "指令发送中…";
  try {
    const response = await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    elements.commandStatus.textContent = "已发送，等待设备确认";
    await poll();
  } catch {
    elements.commandStatus.textContent = "发送失败，请检查 Flask 服务";
  } finally {
    elements.commandButtons.forEach((button) => (button.disabled = false));
  }
};

elements.commandButtons.forEach((button) => {
  button.addEventListener("click", () => sendLedCommand(button.dataset.ledAction));
});

poll();
setInterval(poll, 500);
new ResizeObserver(drawWaveform).observe(elements.adcChart);
