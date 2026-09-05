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
        "devices": {
            role: {"online": devices[role]["online"], "led": devices[role]["led"]}
            for role in sorted(ALLOWED_ROLES)
        },
    }
    return json.dumps(compact_state, ensure_ascii=False)


# 构造系统提示，要求模型只返回项目定义的 JSON 控制计划。
def build_system_prompt(state_text):
    return f"""你是 ESP8266 灯光控制助手。只理解用户意图并生成受限控制计划。
当前状态：{state_text}

设备名称映射：主机=master，A从机=slave_a，B从机=slave_b，C从机=slave_c。
模式：automatic 表示 A0 阈值自动联动，manual 表示四盏灯可分别控制。
只返回一个 JSON 对象，不要 Markdown：
{{"reply":"简短中文回复","actions":[...]}}
允许的动作只有：
{{"type":"set_mode","mode":"automatic或manual"}}
{{"type":"set_led","role":"master或slave_a或slave_b或slave_c","on":true或false}}
规则：
1. 用户要控制任一灯时，如果当前是 automatic，先加入 set_mode=manual，再加入灯动作。
2. 用户说开启自动检测、阈值检测或自动模式时，只设置 automatic，不再设置单灯。
3. 用户只问状态时 actions 返回空数组，并根据当前状态回答。
4. 不允许修改阈值、网络、ADC、采样率或执行任何其他操作。
5. 不确定用户要控制什么时 actions 返回空数组，并在 reply 中请用户说清楚。
"""


# 调用 DeepSeek，并返回模型给出的 JSON 对象。
def request_control_plan(message, state):
    # normalized_message 是清理首尾空白后的用户原话。
    normalized_message = message.strip()
    if not normalized_message:
        raise AssistantError("请输入要执行的操作。")
    if len(normalized_message) > MAX_MESSAGE_LENGTH:
        raise AssistantError(f"单次输入不能超过 {MAX_MESSAGE_LENGTH} 个字符。")

    load_local_environment()
    # api_key 只在 Flask 进程内使用，不会返回浏览器。
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise AssistantError("服务端尚未配置 DeepSeek API Key。")

    # payload 是发送给 DeepSeek 的 OpenAI 兼容请求体。
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": build_system_prompt(build_state_text(state))},
            {"role": "user", "content": normalized_message},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
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
        # content 是模型按 JSON Output 模式生成的控制计划文本。
        content = response_data["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise AssistantError("DeepSeek 返回的控制计划格式无效。") from error


# 严格校验模型提出的动作，任何未知字段或取值都不会执行。
def validate_control_plan(plan):
    if not isinstance(plan, dict):
        raise AssistantError("DeepSeek 没有返回有效的控制计划。")
    # reply 是显示在对话框中的中文回复。
    reply = plan.get("reply")
    # actions 是待执行的模式或灯光操作列表。
    actions = plan.get("actions")
    if not isinstance(reply, str) or not reply.strip():
        raise AssistantError("DeepSeek 回复内容为空。")
    if len(reply) > 500:
        raise AssistantError("DeepSeek 回复内容过长。")
    if not isinstance(actions, list) or len(actions) > MAX_ACTIONS:
        raise AssistantError("DeepSeek 返回的动作数量无效。")

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
    return reply.strip(), validated_actions
