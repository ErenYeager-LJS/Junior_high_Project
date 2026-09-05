import unittest
from unittest.mock import patch

from server import app as server_app
from server.deepseek_assistant import (
    UNSUPPORTED_FUNCTION_MESSAGE,
    AssistantError,
    normalize_history,
    validate_control_plan,
)


# AssistantPlanTests 验证模型输出在执行前必须满足本地安全边界。
class AssistantPlanTests(unittest.TestCase):
    # test_chat_cannot_control 确认普通聊天不能夹带设备动作。
    def test_chat_cannot_control(self):
        # plan 模拟模型错误地在聊天回复中加入开灯动作。
        plan = {
            "intent": "chat",
            "reply": "可以聊聊。",
            "weather_city": None,
            "actions": [{"type": "set_led", "role": "master", "on": True}],
        }
        with self.assertRaisesRegex(AssistantError, f"^{UNSUPPORTED_FUNCTION_MESSAGE}$"):
            validate_control_plan(plan)

    # test_control_action_is_whitelisted 确认合法控制动作能够通过校验。
    def test_control_action_is_whitelisted(self):
        # plan 模拟切换手动模式并打开 B 从机的合法计划。
        plan = {
            "intent": "control",
            "reply": "好，B 灯打开。",
            "weather_city": None,
            "actions": [
                {"type": "set_mode", "mode": "manual"},
                {"type": "set_led", "role": "slave_b", "on": True},
            ],
        }
        # validated 是经过字段过滤后的执行计划。
        validated = validate_control_plan(plan)
        self.assertEqual(validated["intent"], "control")
        self.assertEqual(len(validated["actions"]), 2)

    # test_lighting_preset_is_whitelisted 确认两种组合模式能通过动作白名单。
    def test_lighting_preset_is_whitelisted(self):
        # plan 模拟用户要求切换到模式 1 时模型返回的单一动作。
        plan = {
            "intent": "control",
            "reply": "好，切换到模式 1。",
            "weather_city": None,
            "actions": [{"type": "set_preset", "preset": "mode_1"}],
        }
        # validated 是经过本地白名单校验后的模式动作。
        validated = validate_control_plan(plan)
        self.assertEqual(validated["actions"], [{"type": "set_preset", "preset": "mode_1"}])

    # test_weather_requires_empty_actions 确认天气查询只能读取数据，不能控制灯。
    def test_weather_requires_empty_actions(self):
        # plan 模拟一个只请求南京天气的合法计划。
        plan = {
            "intent": "weather",
            "reply": "我查一下南京。",
            "weather_city": "南京",
            "actions": [],
        }
        # validated 是通过校验的天气意图。
        validated = validate_control_plan(plan)
        self.assertEqual(validated["weather_city"], "南京")
        self.assertEqual(validated["actions"], [])

    # test_history_is_bounded 确认只向模型提供最近八条历史消息。
    def test_history_is_bounded(self):
        # history 模拟十条连续用户消息。
        history = [{"role": "user", "content": f"消息 {index}"} for index in range(10)]
        # normalized 是长度受限的安全历史。
        normalized = normalize_history(history)
        self.assertEqual(len(normalized), 8)
        self.assertEqual(normalized[0]["content"], "消息 2")


# AssistantEndpointTests 验证 Flask 对话接口会按意图调用正确的数据源。
class AssistantEndpointTests(unittest.TestCase):
    # setUp 为每个测试创建不会启动真实服务器的 Flask 客户端。
    def setUp(self):
        self.client = server_app.app.test_client()
        server_app.assistant_requests.clear()
        server_app.control["threshold_enabled"] = True
        server_app.control["manual_led"].update({role: False for role in server_app.DEVICE_ROLES})

    # test_lighting_presets_are_atomic 确认两个网页模式会一次写入互为相反的四灯状态。
    def test_lighting_presets_are_atomic(self):
        # mode_1_response 是网页点击模式 1 后收到的服务端结果。
        mode_1_response = self.client.post("/api/lighting-preset/mode_1", json={})
        self.assertEqual(mode_1_response.status_code, 200)
        self.assertEqual(
            mode_1_response.get_json()["led_states"],
            {"master": False, "slave_a": True, "slave_b": True, "slave_c": True},
        )
        self.assertFalse(server_app.control["threshold_enabled"])

        # mode_2_response 是紧接着切换到相反组合后的服务端结果。
        mode_2_response = self.client.post("/api/lighting-preset/mode_2", json={})
        self.assertEqual(mode_2_response.status_code, 200)
        self.assertEqual(
            mode_2_response.get_json()["led_states"],
            {"master": True, "slave_a": False, "slave_b": False, "slave_c": False},
        )

    # test_weather_intent_uses_realtime_source 确认天气回答来自服务端实时数据。
    @patch.object(server_app, "request_weather_reply", return_value="南京现在大致晴朗，28.2 摄氏度。")
    @patch.object(server_app, "get_current_weather")
    @patch.object(server_app, "request_control_plan")
    def test_weather_intent_uses_realtime_source(self, request_plan, get_weather, weather_reply):
        # request_plan 返回模型识别出的南京天气意图。
        request_plan.return_value = {
            "intent": "weather",
            "reply": "我查一下。",
            "weather_city": "南京",
            "actions": [],
        }
        # get_weather 返回固定观测，避免测试依赖外部网络。
        get_weather.return_value = {"city": "南京", "temperature_c": 28.2, "source": "Open-Meteo"}
        # response 是模拟网页发出的天气询问。
        response = self.client.post("/api/assistant-command", json={"message": "南京现在天气如何？"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["intent"], "weather")
        get_weather.assert_called_once_with("南京")
        weather_reply.assert_called_once()

    # test_time_context_uses_china_standard_time 确认模型看到带 UTC+8 的本地时间。
    def test_time_context_uses_china_standard_time(self):
        # state 是服务端在当前时刻生成的助手上下文。
        state = server_app.assistant_state(0)
        self.assertTrue(state["local_time"].endswith("+08:00"))


# 直接执行本文件时启动标准 unittest 测试运行器。
if __name__ == "__main__":
    unittest.main()
