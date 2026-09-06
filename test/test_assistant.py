import unittest
from unittest.mock import patch

from server import app as server_app
from server.deepseek_assistant import (
    AssistantError,
    build_state_text,
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
        with self.assertRaisesRegex(AssistantError, "不应执行"):
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

    # test_dynamic_tf_preset_is_whitelisted 确认 TF 卡动态模式和本次时间能通过动作白名单。
    def test_dynamic_tf_preset_is_whitelisted(self):
        # plan 模拟用户要求自定义模式运行 23 秒时模型返回的动作。
        plan = {
            "intent": "control",
            "reply": "好，晚自习模式运行 23 秒。",
            "weather_city": None,
            "actions": [{"type": "set_preset", "preset": "mode_custom_7", "duration_seconds": 23}],
        }
        # validated 是经过本地白名单校验后的模式动作。
        validated = validate_control_plan(plan, {"mode_1", "mode_custom_7"})
        self.assertEqual(
            validated["actions"],
            [{"type": "set_preset", "preset": "mode_custom_7", "duration_seconds": 23}],
        )

    # test_unknown_tf_preset_is_rejected 确认模型不能执行卡内不存在的模式编号。
    def test_unknown_tf_preset_is_rejected(self):
        # plan 模拟模型引用了一条已经从 TF 卡删除的模式。
        plan = {
            "intent": "control", "reply": "准备执行。", "weather_city": None,
            "actions": [{"type": "set_preset", "preset": "missing", "duration_seconds": 10}],
        }
        with self.assertRaisesRegex(AssistantError, "无法安全执行"):
            validate_control_plan(plan, {"mode_1"})

    # test_project_state_contains_tf_modes 确认模型上下文包含动态模式和 TF 卡状态。
    def test_project_state_contains_tf_modes(self):
        # state 模拟服务端提供给 DeepSeek 的完整项目状态。
        state = {
            "threshold_enabled": True, "slave_over_threshold": False,
            "threshold_voltage": 0.6, "adc_voltage": 0.2,
            "local_time": "2026-09-06T01:00:00+08:00", "tf_card_ready": True,
            "tf_modes": [{"id": "mode_custom_2", "name": "晚自习", "led_states": {}}],
            "active_timed_mode": {"id": None, "name": None, "deadline": None},
            "devices": {role: {"online": True, "led": False} for role in server_app.DEVICE_ROLES},
        }
        # state_text 是实际送入系统提示的 JSON 文本。
        state_text = build_state_text(state)
        self.assertIn("晚自习", state_text)
        self.assertIn('"ready": true', state_text)

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
        server_app.cancel_timed_mode()

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

    # test_ina219_current_reaches_master_config 确认从机 A 电流会转发给主机。
    def test_ina219_current_reaches_master_config(self):
        # report 模拟 INA219 在 0.1 A 稳定输入下的真实上报。
        report = self.client.post("/api/device-status", json={
            "role": "slave_a", "led": False, "ina219_ready": True,
            "current_ma": 100.25,
        })
        self.assertEqual(report.status_code, 200)
        # master_config 是主机下一轮收到并交给 TFT 的配置。
        master_config = self.client.get("/api/device-config/master").get_json()
        self.assertTrue(master_config["ina219_ready"])
        self.assertAlmostEqual(master_config["slave_current_ma"], 100.25)

    # test_relay_command_enters_manual_mode 确认继电器命令会退出自动模式并控制 A 的 GPIO4。
    def test_relay_command_enters_manual_mode(self):
        # response 模拟网页点击“吸合”按钮。
        response = self.client.post("/api/relay-command", json={"on": True})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(server_app.control["threshold_enabled"])
        self.assertTrue(server_app.control["manual_led"]["slave_a"])
        self.assertTrue(response.get_json()["relay_on"])

        # release 模拟网页点击“释放”按钮。
        release = self.client.post("/api/relay-command", json={"on": False})
        self.assertEqual(release.status_code, 200)
        self.assertFalse(server_app.control["manual_led"]["slave_a"])

    # test_same_mode_accepts_different_run_times 确认同一组合每次都能使用不同时间。
    def test_same_mode_accepts_different_run_times(self):
        # first 是第一次让模式 1 运行 2 秒的响应。
        first = self.client.post("/api/tf-modes/mode_1/activate", json={"duration_seconds": 2})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["duration_seconds"], 2)
        # second 是紧接着改为运行 5 秒的响应。
        second = self.client.post("/api/tf-modes/mode_1/activate", json={"duration_seconds": 5})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["duration_seconds"], 5)
        # remaining 是服务端重新计算后的第二次倒计时，应接近 5 秒而非沿用 2 秒。
        remaining = self.client.get("/api/dashboard").get_json()["active_timed_mode"]["remaining_seconds"]
        self.assertGreaterEqual(remaining, 4)

    # test_new_mode_does_not_store_duration 确认新模式只持久化灯光组合。
    def test_new_mode_does_not_store_duration(self):
        server_app.tf_mode_state.update(card_ready=True, pending_command=None)
        # response 是不带持续时间的新建模式请求。
        response = self.client.post("/api/tf-modes", json={
            "name": "无固定时间", "led_states": {
                "master": True, "slave_a": False, "slave_b": True, "slave_c": False,
            },
        })
        self.assertEqual(response.status_code, 202)
        # record 是准备写入 TF 卡的紧凑文本，保留字段固定为 0。
        record = server_app.tf_mode_state["pending_command"]["record"]
        self.assertIn("|0|1|0|1|0", record)
        server_app.tf_mode_state["pending_command"] = None

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
