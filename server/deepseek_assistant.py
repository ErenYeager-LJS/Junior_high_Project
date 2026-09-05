import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# DeepSeek 对话补全接口地址。
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
# 当前账户可用的快速对话模型。
DEEPSEEK_MODEL = "deepseek-v4-flash"
# 等待 DeepSeek 返回结果的最长秒数。
DEEPSEEK_TIMEOUT_SECONDS = 25
# 用户单次指令允许的最大字符数。
MAX_MESSAGE_LENGTH = 300
# 模型最多可以在一次对话中提出的动作数量。
MAX_ACTIONS = 5
# AI 可以控制的设备角色白名单。
ALLOWED_ROLES = {"master", "slave_a", "slave_b", "slave_c"}
# AI 可以切换的模式白名单。
ALLOWED_MODES = {"automatic", "manual"}
# AI 可以识别的对话意图白名单。
ALLOWED_INTENTS = {"chat", "control", "time", "weather"}
# 浏览器最多向模型补充的历史消息条数。
MAX_HISTORY_MESSAGES = 8


# AssistantError 表示可以安全显示给网页用户的对话处理错误。
class AssistantError(Exception):
    pass


# 从 server/.env 读取本地配置；已存在的系统环境变量优先。
def load_local_environment():
    # env_path 是不会提交到 Git 的本地密钥文件。
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        # line 是去掉首尾空白后的单行配置。
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        # name 和 value 分别是环境变量名与值。
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())


# 把当前设备状态整理成只含控制所需字段的文本，交给模型判断。
def build_state_text(state):
    # devices 保存四块设备的在线状态和 LED 状态。
    devices = state["devices"]
    # compact_state 避免把无关波形和网络信息发送给模型。
    compact_state = {
        "mode": "automatic" if state["threshold_enabled"] else "manual",
        "a_over_threshold": state["slave_over_threshold"],
        "local_time": state["local_time"],
        "devices": {
            role: {"online": devices[role]["online"], "led": devices[role]["led"]}
            for role in sorted(ALLOWED_ROLES)
        },
    }
    return json.dumps(compact_state, ensure_ascii=False)


# 构造系统提示，让模型先判断聊天、实时信息或设备控制意图。
def build_system_prompt(state_text):
    return f"""你是一个沉着、自然、简洁的中文智能助手，同时可以控制 ESP8266 灯光。
当前状态：{state_text}

设备名称映射：主机=master，A从机=slave_a，B从机=slave_b，C从机=slave_c。
模式：automatic 表示 A0 阈值自动联动，manual 表示四盏灯可分别控制。
只返回一个 JSON 对象，不要 Markdown：
{{"intent":"chat或control或time或weather","reply":"自然的中文回复","weather_city":null,"actions":[]}}
允许的动作只有：
{{"type":"set_mode","mode":"automatic或manual"}}
{{"type":"set_led","role":"master或slave_a或slave_b或slave_c","on":true或false}}
规则：
1. 自己判断意图：普通交流用 chat；设备操作或设备状态用 control；当前日期时间用 time；实时天气用 weather。
2. chat、time、weather 的 actions 必须为空。time 必须依据当前状态中的 local_time 回答，不要猜测。
3. weather 只提取城市到 weather_city，reply 先写一句简短过渡；不要凭模型知识编造实时天气。没有城市时 weather_city=null，并请用户补充城市。
4. 用户要控制任一灯时，如果当前是 automatic，先加入 set_mode=manual，再加入灯动作。
5. 用户说开启自动检测、阈值检测或自动模式时，只设置 automatic，不再设置单灯。
6. 用户只问设备状态时使用 control，actions 返回空数组，并根据当前状态回答。
7. 不允许修改阈值、网络、ADC、采样率或执行动作白名单之外的任何操作。
8. 回复像自然对话：直接回答，不说“已为您”“操作成功”“有什么需要尽管说”等模板话，不复述用户整句话，不虚构信息。
9. 控制意图只简短确认理解，例如“好，B 灯打开。”，不要声称硬件已经完成；真实执行结果由后端单独显示。
"""


# normalize_history 校验并清理浏览器传来的短期对话记录。
def normalize_history(history):
    if history is None:
        return []
    if not isinstance(history, list):
        raise AssistantError("对话历史格式无效。")
    # normalized_history 只保留用户和助手的纯文本消息。
    normalized_history = []
    for item in history[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            raise AssistantError("对话历史包含无效消息。")
        # role 是历史消息的发言方。
        role = item.get("role")
        # content 是经过清理的历史消息正文。
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            raise AssistantError("对话历史包含无效角色或内容。")
        content = content.strip()
        if not content or len(content) > 500:
            raise AssistantError("对话历史消息为空或过长。")
        normalized_history.append({"role": role, "content": content})
    return normalized_history


# call_deepseek 发送一次结构化对话请求并解析 JSON 回复。
def call_deepseek(messages, temperature=0.35):
    load_local_environment()
    # api_key 只在 Flask 进程内使用，不会返回浏览器。
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise AssistantError("服务端尚未配置 DeepSeek API Key。")

    # payload 是发送给 DeepSeek 的 OpenAI 兼容请求体。
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": temperature,
        "stream": False,
    }
    # request 包含 JSON 请求体和 Bearer 认证头。
    request = Request(
        DEEPSEEK_API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=DEEPSEEK_TIMEOUT_SECONDS) as response:
            # response_data 是 DeepSeek 返回的完整响应对象。
            response_data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise AssistantError(f"DeepSeek 请求失败，HTTP {error.code}。") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise AssistantError("DeepSeek 暂时无法连接，请稍后重试。") from error

    try:
        # content 是模型按 JSON Output 模式生成的结构化文本。
        content = response_data["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise AssistantError("DeepSeek 返回的数据格式无效。") from error


# 调用 DeepSeek，让模型判断意图并返回受限执行计划。
def request_control_plan(message, state, history=None):
    # normalized_message 是清理首尾空白后的用户原话。
    normalized_message = message.strip()
    if not normalized_message:
        raise AssistantError("请输入要执行的操作。")
    if len(normalized_message) > MAX_MESSAGE_LENGTH:
        raise AssistantError(f"单次输入不能超过 {MAX_MESSAGE_LENGTH} 个字符。")

    # messages 按系统提示、短期历史、当前消息的顺序发送。
    messages = [
        {"role": "system", "content": build_system_prompt(build_state_text(state))},
        *normalize_history(history),
        {"role": "user", "content": normalized_message},
    ]
    return call_deepseek(messages)


# request_weather_reply 让模型把可信天气数据整理成自然、简短的回答。
def request_weather_reply(message, weather_data):
    # weather_text 是模型唯一可以引用的实时天气事实。
    weather_text = json.dumps(weather_data, ensure_ascii=False)
    # messages 明确要求模型不得修改或补造观测数据。
    messages = [
        {
            "role": "system",
            "content": (
                "你是沉着、自然的中文智能助手。根据给定实时天气 JSON 回答用户，"
                "只返回 JSON：{\"reply\":\"中文回复\"}。先说天气结论，再按用户问题选用当前温度、"
                "体感、湿度、风速、降水或今日高低温与降水概率；最后可给一句克制实用的建议。不要堆砌所有字段，不要编造 JSON 外的信息，"
                "不要使用夸张语气或模板化客套话。"
            ),
        },
        {"role": "user", "content": f"用户问题：{message}\n实时天气：{weather_text}"},
    ]
    # response 是 DeepSeek 生成的天气回答对象。
    response = call_deepseek(messages, temperature=0.45)
    # reply 是最终显示和朗读的中文内容。
    reply = response.get("reply") if isinstance(response, dict) else None
    if not isinstance(reply, str) or not reply.strip() or len(reply) > 700:
        raise AssistantError("DeepSeek 返回的天气回复无效。")
    return reply.strip()


# 严格校验模型提出的动作，任何未知字段或取值都不会执行。
def validate_control_plan(plan):
    if not isinstance(plan, dict):
        raise AssistantError("DeepSeek 没有返回有效的控制计划。")
    # reply 是显示在对话框中的中文回复。
    reply = plan.get("reply")
    # actions 是待执行的模式或灯光操作列表。
    actions = plan.get("actions")
    # intent 是模型判断出的请求类型。
    intent = plan.get("intent")
    # weather_city 是天气查询需要的城市名，其他意图应为空。
    weather_city = plan.get("weather_city")
    if intent not in ALLOWED_INTENTS:
        raise AssistantError("DeepSeek 返回了无法识别的对话意图。")
    if not isinstance(reply, str) or not reply.strip():
        raise AssistantError("DeepSeek 回复内容为空。")
    if len(reply) > 500:
        raise AssistantError("DeepSeek 回复内容过长。")
    if not isinstance(actions, list) or len(actions) > MAX_ACTIONS:
        raise AssistantError("DeepSeek 返回的动作数量无效。")
    if intent != "control" and actions:
        raise AssistantError("非控制类对话不能执行设备操作。")
    if weather_city is not None and (not isinstance(weather_city, str) or len(weather_city.strip()) > 80):
        raise AssistantError("DeepSeek 返回的城市名称无效。")
    if intent != "weather" and weather_city is not None:
        raise AssistantError("非天气类对话不能请求城市天气。")

    # validated_actions 只保存通过白名单校验的动作。
    validated_actions = []
    for action in actions:
        if not isinstance(action, dict):
            raise AssistantError("DeepSeek 返回了无法识别的动作。")
        # action_type 表示切换模式或设置 LED。
        action_type = action.get("type")
        if action_type == "set_mode" and action.get("mode") in ALLOWED_MODES:
            validated_actions.append({"type": action_type, "mode": action["mode"]})
        elif (
            action_type == "set_led"
            and action.get("role") in ALLOWED_ROLES
            and isinstance(action.get("on"), bool)
        ):
            validated_actions.append(
                {"type": action_type, "role": action["role"], "on": action["on"]}
            )
        else:
            raise AssistantError("DeepSeek 提出了项目不允许执行的操作。")
    return {
        "intent": intent,
        "reply": reply.strip(),
        "weather_city": weather_city.strip() if isinstance(weather_city, str) else None,
        "actions": validated_actions,
    }
