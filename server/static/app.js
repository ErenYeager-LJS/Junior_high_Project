// elements 集中保存页面中需要读写的控件，避免重复查询 DOM。
const elements = {
  networkState: document.querySelector("#networkState"),
  thresholdEnabled: document.querySelector("#thresholdEnabled"),
  modeLabel: document.querySelector("#modeLabel"),
  alertBand: document.querySelector("#alertBand"),
  commandStatus: document.querySelector("#commandStatus"),
  manualButtons: document.querySelectorAll("[data-role][data-led]"),
  adcChart: document.querySelector("#adcChart"),
  assistantForm: document.querySelector("#assistantForm"),
  assistantInput: document.querySelector("#assistantInput"),
  assistantSend: document.querySelector("#assistantSend"),
  assistantStatus: document.querySelector("#assistantStatus"),
  chatLog: document.querySelector("#chatLog"),
  speakReplies: document.querySelector("#speakReplies"),
  assistantShortcut: document.querySelector("#assistantShortcut"),
};

// waveform 保存网页当前绘制的 A0 采样点。
let waveform = [];
// thresholdRaw 保存 0.600 V 对应的 ADC 原始阈值。
let thresholdRaw = 614;
// chatHistory 保存最近几轮成功对话，让助手能够理解连续追问。
let chatHistory = [];
// preferredVoice 保存浏览器中最接近沉稳中文助理风格的语音。
let preferredVoice = null;

// setText 设置指标文本；没有数据时统一显示破折号。
const setText = (id, value) => {
  document.querySelector(`#${id}`).textContent = value ?? "—";
};

// renderDevice 把一块设备的在线、LED 和地址状态更新到对应卡片。
const renderDevice = (role, device) => {
  setText(`${role}Online`, device.online ? "在线" : "离线");
  setText(`${role}Led`, device.led === null ? "等待上报" : device.led ? "亮" : "灭");
  setText(`${role}Ip`, device.device_ip);
  document.querySelector(`[data-device="${role}"]`).dataset.online = String(device.online);
  document.querySelector(`#${role}Lamp`).dataset.on = String(device.led === true);
};

// cssColor 读取 CSS 设计令牌，供 Canvas 使用同一套颜色和字体。
const cssColor = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// drawWaveform 根据当前采样点和容器尺寸重绘 A0 波形。
const drawWaveform = () => {
  // canvas 是显示 ADC 波形的画布元素。
  const canvas = elements.adcChart;
  // bounds 是画布在页面上的实际 CSS 尺寸。
  const bounds = canvas.getBoundingClientRect();
  // scale 限制高分屏倍率，兼顾清晰度和绘图开销。
  const scale = Math.min(window.devicePixelRatio || 1, 2);
  // width 和 height 是用于绘图的 CSS 像素尺寸。
  const width = Math.max(1, Math.round(bounds.width));
  const height = Math.max(1, Math.round(bounds.height));
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  // context 是执行二维线条和文字绘制的画布上下文。
  const context = canvas.getContext("2d");
  context.scale(scale, scale);
  context.clearRect(0, 0, width, height);
  // pad 为坐标标签和阈值线预留四周空间。
  const pad = { top: 18, right: 14, bottom: 28, left: 44 };
  // plotWidth 和 plotHeight 是数据曲线实际可用的绘图区域。
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  context.font = `11px ${cssColor("--font-mono")}`;
  context.strokeStyle = cssColor("--color-rule");
  context.fillStyle = cssColor("--color-muted");
  context.textAlign = "right";
  [0, 256, 512, 768, 1023].forEach((value) => {
    // y 是当前 ADC 刻度在画布上的纵坐标。
    const y = pad.top + plotHeight - (value / 1023) * plotHeight;
    context.beginPath(); context.moveTo(pad.left, y); context.lineTo(width - pad.right, y); context.stroke();
    if ([0, 512, 1023].includes(value)) context.fillText(String(value), pad.left - 7, y + 4);
  });
  // thresholdY 是 0.600 V 阈值虚线的纵坐标。
  const thresholdY = pad.top + plotHeight - (thresholdRaw / 1023) * plotHeight;
  context.setLineDash([6, 5]);
  context.strokeStyle = cssColor("--color-warning");
  context.beginPath(); context.moveTo(pad.left, thresholdY); context.lineTo(width - pad.right, thresholdY); context.stroke();
  context.setLineDash([]);
  if (!waveform.length) return;
  // end 是最后一个采样点的毫秒时间戳。
  const end = waveform.at(-1).timestamp_ms;
  // start 是最近十五秒显示窗口的起点。
  const start = end - 15000;
  // visible 只保留当前时间窗口内的采样点。
  const visible = waveform.filter((point) => point.timestamp_ms >= start);
  context.strokeStyle = cssColor("--color-accent");
  context.lineWidth = 2;
  context.beginPath();
  visible.forEach((point, index) => {
    // x 和 y 把采样时间与原始值映射到画布坐标。
    const x = pad.left + ((point.timestamp_ms - start) / 15000) * plotWidth;
    const y = pad.top + plotHeight - (point.value / 1023) * plotHeight;
    index ? context.lineTo(x, y) : context.moveTo(x, y);
  });
  context.stroke();
};

// render 使用一次仪表盘响应刷新全部设备、模式、告警和波形。
const render = (status) => {
  // 四个变量分别保存主机与 A/B/C 从机的状态。
  const { master, slave_a, slave_b, slave_c } = status.devices;
  renderDevice("master", master);
  renderDevice("slave_a", slave_a);
  renderDevice("slave_b", slave_b);
  renderDevice("slave_c", slave_c);
  // allOnline 只有在四块设备都在线时才为 true。
  const allOnline = master.online && slave_a.online && slave_b.online && slave_c.online;
  elements.networkState.dataset.online = String(allOnline);
  elements.networkState.lastElementChild.textContent = allOnline ? "四台设备在线" : "设备未全部在线";
  elements.thresholdEnabled.checked = status.threshold_enabled;
  elements.modeLabel.textContent = status.threshold_enabled ? "自动检测" : "手动控制";
  elements.manualButtons.forEach((button) => (button.disabled = status.threshold_enabled));
  elements.alertBand.hidden = !status.alert_message;
  setText("adcVoltage", Number.isFinite(status.adc_voltage) ? `${status.adc_voltage.toFixed(3)} V` : null);
  setText("adcRaw", slave_a.adc_latest);
  setText("thresholdResult", status.slave_over_threshold ? "超过 0.600 V" : "未超过阈值");
  setText("masterAlert", status.alert_message || "无告警");
  setText("sampleRate", Number.isFinite(status.effective_sample_rate_hz) ? `${status.effective_sample_rate_hz} Hz（目标 ${status.sample_rate_hz}）` : null);
  setText("adcRange", Number.isFinite(status.adc_min) ? `${status.adc_min}–${status.adc_max}` : null);
  waveform = status.waveform || [];
  thresholdRaw = status.threshold_raw;
  drawWaveform();
};

// requestJson 发送 JSON POST 请求，并把后端错误转换成可显示异常。
const requestJson = async (url, body) => {
  // response 是浏览器收到的原始 HTTP 响应。
  const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  // result 是解析后的 JSON；空响应会退回空对象。
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
};

// appendChatMessage 把用户、助手、系统或错误消息追加到对话区。
const appendChatMessage = (text, kind) => {
  // message 是即将加入对话区的单条消息元素。
  const message = document.createElement("p");
  message.className = `chat-message ${kind}-message`;
  message.textContent = text;
  elements.chatLog.append(message);
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
};

// choosePreferredVoice 从系统语音中优先选择自然、低沉的中文男声。
const choosePreferredVoice = () => {
  if (!("speechSynthesis" in window)) return null;
  // voices 是浏览器当前可用的全部系统语音。
  const voices = window.speechSynthesis.getVoices();
  // preferredNames 按自然度和沉稳程度排列常见的中文语音名称。
  const preferredNames = ["Yunyang", "Yunxi", "Kangkang", "云扬", "云希", "Microsoft"];
  // chineseVoices 只保留普通话或中文语音。
  const chineseVoices = voices.filter((voice) => voice.lang.toLowerCase().startsWith("zh"));
  preferredVoice = chineseVoices.find((voice) => preferredNames.some((name) => voice.name.includes(name)))
    || chineseVoices[0]
    || voices[0]
    || null;
  return preferredVoice;
};

// speakReply 使用选定的沉稳中文系统声线朗读助手回复。
const speakReply = (text) => {
  if (!elements.speakReplies.checked || !("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  // utterance 保存本次朗读的文本、语言和声音参数。
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.voice = preferredVoice || choosePreferredVoice();
  utterance.rate = 0.9;
  utterance.pitch = 0.78;
  utterance.volume = 0.96;
  window.speechSynthesis.speak(utterance);
};

// sendAssistantMessage 提交当前输入并显示分类、回答和执行结果。
const sendAssistantMessage = async () => {
  // message 是去除首尾空白后的本次用户输入。
  const message = elements.assistantInput.value.trim();
  if (!message) return;
  appendChatMessage(message, "user");
  elements.assistantInput.value = "";
  elements.assistantSend.disabled = true;
  elements.assistantForm.dataset.state = "loading";
  elements.assistantStatus.textContent = "正在思考";
  try {
    // result 是后端完成意图判断、工具调用和白名单控制后的结果。
    const result = await requestJson("/api/assistant-command", { message, history: chatHistory });
    appendChatMessage(result.reply, "assistant");
    if (result.executed?.length) appendChatMessage(result.executed.join(" · "), "system");
    // chatHistory 只记录自然对话正文，不把内部执行说明送回模型。
    chatHistory = [
      ...chatHistory,
      { role: "user", content: message },
      { role: "assistant", content: result.reply },
    ].slice(-8);
    speakReply(result.reply);
    elements.assistantStatus.textContent = "";
    elements.assistantForm.dataset.state = "success";
    await poll();
  } catch (error) {
    appendChatMessage(error.message || "指令执行失败。", "error");
    elements.assistantStatus.textContent = "请求失败";
    elements.assistantForm.dataset.state = "error";
  } finally {
    elements.assistantSend.disabled = false;
    elements.assistantInput.focus();
    window.setTimeout(() => delete elements.assistantForm.dataset.state, 1200);
  }
};

// poll 每半秒获取一次仪表盘快照，保持设备状态和波形实时更新。
const poll = async () => {
  try {
    // response 是仪表盘状态接口的原始响应。
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch {
    elements.networkState.dataset.online = "false";
    elements.networkState.lastElementChild.textContent = "网站连接中断";
  }
};

// 自动检测开关变化时，把新模式写入 Flask。
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

// 每个手动按钮把目标设备和灯状态发送给 Flask。
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

// 表单提交时阻止页面刷新，改用异步对话接口。
elements.assistantForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await sendAssistantMessage();
});

// 输入框中按 Enter 发送，Shift+Enter 仍用于换行。
elements.assistantInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.assistantForm.requestSubmit();
  }
});

// 对话快捷按钮把键盘焦点移动到消息输入框。
elements.assistantShortcut.addEventListener("click", () => {
  document.querySelector("#assistantSection").scrollIntoView({ behavior: "smooth", block: "start" });
  elements.assistantInput.focus({ preventScroll: true });
});

// voiceschanged 会在浏览器异步载入系统语音后重新选择声线。
if ("speechSynthesis" in window) {
  choosePreferredVoice();
  window.speechSynthesis.addEventListener("voiceschanged", choosePreferredVoice);
}

// Lucide 加载成功时，把占位元素替换成统一的线性图标。
if (window.lucide) window.lucide.createIcons({ attrs: { "stroke-width": 1.8 } });

// 启动时立即获取一次状态，避免页面先空白半秒。
poll();
// dashboardTimer 每半秒触发一次设备状态刷新。
const dashboardTimer = window.setInterval(poll, 500);
// chartResizeObserver 在波形容器尺寸改变后重新绘图。
const chartResizeObserver = new ResizeObserver(drawWaveform);
chartResizeObserver.observe(elements.adcChart);
