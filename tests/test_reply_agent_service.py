import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
SIMAGENT_SRC = ROOT.parent / "SimAgentPlg" / "src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SIMAGENT_SRC))

from simagentplg import ModelConfig

from app.core.context_builder import ContextBuilder
from app.core.group_state import GroupState, TopicState
from app.core.message import normalize_group_message
from app.core.reply import ReplyDecision
from app.services.reply_agent_service import NapcatReplyAgent


DUMMY_CONFIG = ModelConfig(
    model="test-model",
    api_key="test-key",
    base_url="http://example.invalid/v1",
)


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def send_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((action, params))
        return {"ok": True}


class FakeReplyRuntime:
    instances: list["FakeReplyRuntime"] = []

    def __init__(self, *args, handlers=None, **kwargs) -> None:
        self.handler = tuple(handlers or [])[0]
        self.runtime_tasks: list[str] = []
        FakeReplyRuntime.instances.append(self)

    def reset(self) -> None:
        pass

    async def runtime(self, *, task: str) -> str:
        self.runtime_tasks.append(task)
        await self.handler.dispatch(
            "send_at_msg",
            {"user_id": 200, "message": "已经启动了"},
        )
        return "sent"

    async def shutdown(self) -> None:
        pass


class ReplyAgentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_agent_executes_send_at_msg_and_records_state(self) -> None:
        FakeReplyRuntime.instances.clear()
        sender = FakeSender()
        message = normalize_group_message(
            {
                "post_type": "message",
                "message_type": "group",
                "group_id": 100,
                "user_id": 200,
                "message_id": "m1",
                "sender": {"nickname": "A"},
                "message": "蛋总 是否启动成功",
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
        decision = ReplyDecision(
            should_reply=True,
            topic_id=topic.topic_id,
            reply_intent="ANSWER",
            reply_style="short_explain",
            risk_level="normal",
            reply_target="current_user",
            confidence=0.9,
            reason="用户明确询问机器人",
        )
        task = ContextBuilder(bot_name="蛋总").build_action_task(
            message=message,
            topic=topic,
            state=state,
            decision=decision,
        )

        with patch("app.services.reply_agent_service.BaseAgent", FakeReplyRuntime):
            agent = NapcatReplyAgent(sender=sender, config=DUMMY_CONFIG)
            result = await agent.handle_message(
                task=task,
                message=message,
                topic=topic,
                state=state,
                decision=decision,
            )
            await agent.shutdown()

        self.assertEqual(result, "sent")
        self.assertEqual(sender.calls[0][0], "send_group_msg")
        self.assertEqual(sender.calls[0][1]["group_id"], "100")
        self.assertEqual(
            sender.calls[0][1]["message"],
            [
                {"type": "at", "data": {"qq": "200"}},
                {"type": "text", "data": {"text": " 已经启动了"}},
            ],
        )
        self.assertEqual(state.bot_recent_replies, ["@200 已经启动了"])
        self.assertEqual(topic.bot_replied_count, 1)
        self.assertEqual(state.recent_decisions, [decision])
        self.assertIn("should_reply: True", FakeReplyRuntime.instances[0].runtime_tasks[0])


if __name__ == "__main__":
    unittest.main()
