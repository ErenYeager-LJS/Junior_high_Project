// elements 集中保存页面中需要读写的控件，避免重复查询 DOM。
const elements = {
  networkState: document.querySelector("#networkState"),
  tfState: document.querySelector("#tfState"),
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
  modeShortcut: document.querySelector("#modeShortcut"),
  modeDialog: document.querySelector("#modeDialog"),
  modeClose: document.querySelector("#modeClose"),
  modeList: document.querySelector("#modeList"),
  modeCount: document.querySelector("#modeCount"),
  tfCardStatus: document.querySelector("#tfCardStatus"),
  timedModeStatus: document.querySelector("#timedModeStatus"),
  modeForm: document.querySelector("#modeForm"),
  modeName: document.querySelector("#modeName"),
  modeSave: document.querySelector("#modeSave"),
  modeFormStatus: document.querySelector("#modeFormStatus"),
  modeRunForm: document.querySelector("#modeRunForm"),
  selectedModeName: document.querySelector("#selectedModeName"),
  runDuration: document.querySelector("#runDuration"),
  modeRun: document.querySelector("#modeRun"),
};

// waveform 保存网页当前绘制的 A0 采样点。
let waveform = [];
// thresholdRaw 保存 0.600 V 对应的 ADC 原始阈值。
let thresholdRaw = 614;
// chatHistory 保存最近几轮成功对话，让助手能够理解连续追问。
let chatHistory = [];
// preferredVoice 保存浏览器中最接近沉稳中文助理风格的语音。
let preferredVoice = null;
// renderedModeSignature 记录上次模式列表内容，内容未变时不重建窗口 DOM。
let renderedModeSignature = "";
// lastTfCommandPending 保存上一轮写卡等待状态，用于识别主机刚刚确认完成的时刻。
let lastTfCommandPending = false;
// selectedModeId 保存用户先选中的灯光组合，执行时间会在下一步单独读取。
let selectedModeId = null;

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

// makeIconButton 创建带 Lucide 图标、提示和数据属性的模式操作按钮。
const makeIconButton = (iconName, className, title, modeId) => {
  // button 是即将加入某个模式右侧的图标按钮。
  const button = document.createElement("button");
  button.type = "button";
  button.className = `icon-button ${className}`;
  button.title = title;
  button.setAttribute("aria-label", title);
  button.dataset.modeId = modeId;
  // icon 是等待 Lucide 转换成线性图标的占位元素。
  const icon = document.createElement("i");
  icon.dataset.lucide = iconName;
  icon.setAttribute("aria-hidden", "true");
  button.append(icon);
  return button;
};

// renderModeList 把 TF 卡模式绘制到独立窗口，并更新倒计时与同步状态。
const renderModeList = (status) => {
  // modes 是主机最近一次从 TF 卡同步出的全部模式。
  const modes = status.tf_modes || [];
  // activeMode 是当前正在倒计时执行的模式状态。
  const activeMode = status.active_timed_mode || {};
  elements.modeCount.textContent = `${modes.length} / 12`;
  elements.tfCardStatus.textContent = status.tf_write_error
    || (status.tf_command_pending ? "正在写入 TF 卡" : status.tf_card_ready ? "TF 卡已连接" : "TF 卡不可用");
  elements.tfState.dataset.ready = String(status.tf_card_ready && !status.tf_write_error);
  elements.tfState.lastElementChild.textContent = status.tf_write_error
    || (status.tf_command_pending ? "TF 卡写入中" : status.tf_card_ready ? "TF 卡可用" : "TF 卡不可用");
  if (lastTfCommandPending && !status.tf_command_pending) {
    elements.modeFormStatus.textContent = status.tf_write_error || "已同步到 TF 卡";
  }
  lastTfCommandPending = status.tf_command_pending;
  elements.timedModeStatus.textContent = activeMode.id
    ? `${activeMode.name} · 剩余 ${activeMode.remaining_seconds} 秒，结束后恢复自动检测`
    : "A0 高于 0.600 V 时四机同步点亮。";
  elements.modeSave.disabled = !status.tf_card_ready || status.tf_command_pending || modes.length >= 12;

  if (selectedModeId && !modes.some((mode) => mode.id === selectedModeId)) selectedModeId = null;
  // signature 只包含会改变模式卡片结构和选中态的字段。
  const signature = JSON.stringify([
    modes, activeMode.id, selectedModeId, status.tf_card_ready,
    status.tf_command_pending, status.tf_write_error,
  ]);
  if (signature === renderedModeSignature) return;
  renderedModeSignature = signature;
  elements.modeList.replaceChildren();
  modes.forEach((mode) => {
    // item 是一条独立的已保存模式。
    const item = document.createElement("article");
    item.className = "mode-item";
    item.dataset.active = String(mode.id === activeMode.id);
    item.dataset.selected = String(mode.id === selectedModeId);
    // copy 包含模式名称、时长和四盏灯摘要。
    const copy = document.createElement("div");
    copy.className = "mode-item-copy";
    // titleLine 把模式名和持续秒数放在同一行。
    const titleLine = document.createElement("div");
    titleLine.className = "mode-item-title";
    // title 是只使用 textContent 写入的用户模式名称。
    const title = document.createElement("strong");
    title.textContent = mode.name;
    titleLine.append(title);
    // summary 逐个显示主机与三个从机的亮灭设置。
    const summary = document.createElement("div");
    summary.className = "mode-led-summary";
    [["master", "主机"], ["slave_a", "A"], ["slave_b", "B"], ["slave_c", "C"]].forEach(([role, label]) => {
      // state 是当前设备在这个模式中的摘要标签。
      const state = document.createElement("span");
      state.dataset.on = String(mode.led_states[role]);
      state.textContent = `${label} ${mode.led_states[role] ? "亮" : "灭"}`;
      summary.append(state);
    });
    copy.append(titleLine, summary);
    // actions 保存选择和可选的删除图标按钮。
    const actions = document.createElement("div");
    actions.className = "mode-item-actions";
    // selectButton 先选择组合，时间在列表下方的独立执行区输入。
    const selectButton = makeIconButton(
      mode.id === selectedModeId ? "check" : "mouse-pointer-2",
      "select-mode", mode.id === selectedModeId ? `已选择 ${mode.name}` : `选择 ${mode.name}`, mode.id,
    );
    selectButton.setAttribute("aria-pressed", String(mode.id === selectedModeId));
    actions.append(selectButton);
    if (!['mode_1', 'mode_2'].includes(mode.id)) {
      actions.append(makeIconButton("trash-2", "delete-mode", `删除 ${mode.name}`, mode.id));
    }
    item.append(copy, actions);
    elements.modeList.append(item);
  });
  // selectedMode 是本轮选中的完整模式对象。
  const selectedMode = modes.find((mode) => mode.id === selectedModeId);
  elements.selectedModeName.textContent = selectedMode ? selectedMode.name : "先选择一个组合";
  elements.modeRun.disabled = !selectedMode || !status.tf_card_ready;
  if (window.lucide) window.lucide.createIcons({ attrs: { "stroke-width": 1.8 } });
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
  renderModeList(status);
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
    elements.tfState.dataset.ready = "false";
    elements.tfState.lastElementChild.textContent = "TF 卡状态未知";
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

// 顶部模式入口打开独立管理窗口。
elements.modeShortcut.addEventListener("click", () => {
  elements.modeDialog.showModal();
  window.setTimeout(() => document.querySelector(".select-mode")?.focus(), 0);
});

// 关闭按钮退出模式窗口，但不影响正在运行的模式。
elements.modeClose.addEventListener("click", () => elements.modeDialog.close());

// 点击对话框半透明背景时关闭窗口。
elements.modeDialog.addEventListener("click", (event) => {
  if (event.target === elements.modeDialog) elements.modeDialog.close();
});

// 模式列表统一处理选择和删除按钮，列表刷新后无需重复绑定事件。
elements.modeList.addEventListener("click", async (event) => {
  // button 是本次点击位置向上找到的模式操作按钮。
  const button = event.target.closest("button[data-mode-id]");
  if (!button) return;
  // modeId 是 TF 卡内模式的唯一编号。
  const modeId = button.dataset.modeId;
  if (button.classList.contains("select-mode")) {
    selectedModeId = modeId;
    renderedModeSignature = "";
    await poll();
    elements.runDuration.focus({ preventScroll: true });
    return;
  }
  if (!window.confirm("确定从 TF 卡删除这个模式吗？")) return;
  button.disabled = true;
  try {
    await requestJson(`/api/tf-modes/${modeId}/delete`, {});
    elements.modeFormStatus.textContent = "正在从 TF 卡删除";
    await poll();
  } catch (error) {
    elements.modeFormStatus.textContent = error.message || "模式操作失败";
  } finally {
    button.disabled = false;
  }
});

// 执行表单在用户选好组合后，单独提交这一次的持续时间。
elements.modeRunForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedModeId) return;
  // durationSeconds 是本次执行时间，不会保存进 TF 卡组合。
  const durationSeconds = Number.parseInt(elements.runDuration.value, 10);
  elements.modeRun.disabled = true;
  elements.modeFormStatus.textContent = "正在启动模式";
  try {
    // result 是 Flask 实际接受的模式与本次时间。
    const result = await requestJson(`/api/tf-modes/${selectedModeId}/activate`, {
      duration_seconds: durationSeconds,
    });
    elements.modeFormStatus.textContent = `${result.mode.name} 已开始，${result.duration_seconds} 秒后恢复自动检测`;
    await poll();
  } catch (error) {
    elements.modeFormStatus.textContent = error.message || "模式启动失败";
  } finally {
    await poll();
  }
});

// 新建模式表单只把名称和四盏灯状态排队写入 TF 卡。
elements.modeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  // ledStates 逐项读取四个复选框的逻辑状态。
  const ledStates = Object.fromEntries(
    ["master", "slave_a", "slave_b", "slave_c"].map((role) => [role, elements.modeForm.elements[role].checked]),
  );
  elements.modeSave.disabled = true;
  elements.modeFormStatus.textContent = "正在保存到 TF 卡";
  try {
    await requestJson("/api/tf-modes", {
      name: elements.modeName.value.trim(), led_states: ledStates,
    });
    elements.modeForm.reset();
    await poll();
  } catch (error) {
    elements.modeFormStatus.textContent = error.message || "保存失败";
    elements.modeSave.disabled = false;
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
// 带 #modes 的地址直接打开模式窗口，便于收藏和现场快速进入。
if (window.location.hash === "#modes") {
  elements.modeDialog.showModal();
  window.setTimeout(() => document.querySelector(".select-mode")?.focus(), 600);
}
// dashboardTimer 每半秒触发一次设备状态刷新。
const dashboardTimer = window.setInterval(poll, 500);
// chartResizeObserver 在波形容器尺寸改变后重新绘图。
const chartResizeObserver = new ResizeObserver(drawWaveform);
chartResizeObserver.observe(elements.adcChart);
