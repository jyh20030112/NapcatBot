import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
SIMAGENT_SRC = ROOT.parent / "SimAgentPlg" / "src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SIMAGENT_SRC))

from simagentplg import ModelConfig

from app.core.context_builder import ContextBuilder
from app.core.group_state import GroupState, TopicState
from app.core.message import normalize_group_message
from app.services.decision_agent_service import DecisionService


DUMMY_CONFIG = ModelConfig(
    model="test-model",
    api_key="test-key",
    base_url="http://example.invalid/v1",
)


class FakeDecisionRuntime:
    instances: list["FakeDecisionRuntime"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.messages = None
        FakeDecisionRuntime.instances.append(self)

    async def chat_json(self, messages):
        self.messages = messages
        return {
            "should_reply": False,
            "topic_id": "topic_1",
            "reply_intent": "ANSWER",
            "reply_style": "short_explain",
            "risk_level": "normal",
            "reply_target": "current_user",
            "confidence": 0.9,
            "reason": (
                "当前消息直接提到机器人昵称，属于明确向机器人询问。"
                "消息内容是在确认项目启动状态，和当前话题标题及摘要一致。"
                "上下文没有争吵、敏感或引战风险，机器人也没有在该话题中过度重复回复。"
                "因此应该回复当前用户，意图选择 ANSWER，风格使用 short_explain。"
                "这段额外分析用于确认长 reason 不会被过早截断。" * 20
            ),
        }

    async def shutdown(self) -> None:
        pass


class DecisionAgentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_decision_agent_builds_context_and_normalizes_reply_decision(self) -> None:
        FakeDecisionRuntime.instances.clear()
        message = normalize_group_message(
            {
                "post_type": "message",
                "message_type": "group",
                "group_id": 100,
                "user_id": 200,
                "message_id": "m1",
                "sender": {"nickname": "A"},
                "message": "@蛋总 是否启动成功",
            },
            bot_id=123,
            bot_name="蛋总",
        )
        assert message is not None
        state = GroupState(group_id=100)
        state.add_message(message)
        topic = TopicState(
            topic_id="topic_1",
            title="项目启动状态",
            summary="询问项目是否启动成功",
        )
        state.topics[topic.topic_id] = topic
        state.record_topic_message(topic, message)

        with patch("app.services.decision_agent_service.BaseAgent", FakeDecisionRuntime):
            service = DecisionService(
                context_builder=ContextBuilder(bot_name="蛋总"),
                config=DUMMY_CONFIG,
            )
            decision = await service.decide(message=message, topic=topic, state=state)
            await service.shutdown()

        self.assertTrue(decision.should_reply)
        self.assertEqual(decision.reply_intent, "ANSWER")
        self.assertEqual(decision.reply_target, "current_user")
        self.assertGreater(len(decision.reason), 240)
        self.assertLessEqual(len(decision.reason), 1200)
        runtime = FakeDecisionRuntime.instances[0]
        assert runtime.messages is not None
        user_task = runtime.messages[-1]["content"]
        self.assertIn("是否提到机器人昵称: True", user_task)
        self.assertIn("@蛋总 是否启动成功", user_task)


if __name__ == "__main__":
    unittest.main()
