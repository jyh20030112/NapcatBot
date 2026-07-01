import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
SIMAGENT_SRC = ROOT.parent / "SimAgentPlg" / "src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SIMAGENT_SRC))

from simagentplg import ModelConfig

from app.core.context_builder import ContextBuilder
from app.core.group_state import GroupState
from app.core.message import normalize_group_message
from app.core.topic_store import TopicStore
from app.services.topic_agent_service import TopicAgentService


DUMMY_CONFIG = ModelConfig(
    model="test-model",
    api_key="test-key",
    base_url="http://example.invalid/v1",
)


class FakeTopicRuntime:
    def __init__(self, *args, handlers=None, **kwargs) -> None:
        self.handler = tuple(handlers or [])[0]
        self.runtime_tasks: list[str] = []

    def reset(self) -> None:
        pass

    async def runtime(self, *, task: str) -> str:
        self.runtime_tasks.append(task)
        message = self.handler.current_message
        assert message is not None

        created = await self.handler.dispatch(
            "create_topic",
            {
                "group_id": message.group_id,
                "title": "项目启动状态",
                "summary": "询问项目是否启动成功",
            },
        )
        topic_id = int(created.data["id"])
        await self.handler.dispatch(
            "assign_message_to_topic",
            {
                "group_id": message.group_id,
                "message_id": message.message_id,
                "topic_id": topic_id,
                "msg": message.text,
            },
        )
        return "assigned"

    async def shutdown(self) -> None:
        pass


class TopicAgentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_topic_agent_creates_and_assigns_current_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TopicStore(Path(temp_dir) / "topics.sqlite3")
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

            with patch("app.services.topic_agent_service.BaseAgent", FakeTopicRuntime):
                service = TopicAgentService(
                    context_builder=ContextBuilder(bot_name="蛋总"),
                    store=store,
                    config=DUMMY_CONFIG,
                )
                topic = await service.assign_topic(message, state)
                await service.shutdown()

            self.assertEqual(topic.topic_id, "topic_1")
            self.assertEqual(topic.title, "项目启动状态")
            self.assertEqual(state.message_topic_map["m1"], "topic_1")
            self.assertEqual(store.get_topic_messages(1, limit=5)[0]["text"], "蛋总 是否启动成功")

    async def test_topic_agent_assigns_reply_to_existing_topic_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TopicStore(Path(temp_dir) / "topics.sqlite3")
            original = normalize_group_message(
                {
                    "post_type": "message",
                    "message_type": "group",
                    "group_id": 100,
                    "user_id": 200,
                    "message_id": "m1",
                    "sender": {"nickname": "A"},
                    "message": "NapCat websocket 怎么接",
                },
                bot_id=123,
                bot_name="蛋总",
            )
            assert original is not None
            topic_row = store.create_topic(
                group_id=100,
                title="NapCat WebSocket",
                summary="讨论 websocket 接入",
            )
            store.assign_message_to_topic(
                group_id=100,
                message=original,
                topic_id=int(topic_row["id"]),
            )
            reply = normalize_group_message(
                {
                    "post_type": "message",
                    "message_type": "group",
                    "group_id": 100,
                    "user_id": 201,
                    "message_id": "m2",
                    "sender": {"nickname": "B"},
                    "message": [
                        {"type": "reply", "data": {"id": "m1"}},
                        {"type": "text", "data": {"text": " 这个我也想看"}},
                    ],
                },
                bot_id=123,
                bot_name="蛋总",
            )
            assert reply is not None
            state = GroupState(group_id=100)

            with patch("app.services.topic_agent_service.BaseAgent", FakeTopicRuntime):
                service = TopicAgentService(
                    context_builder=ContextBuilder(bot_name="蛋总"),
                    store=store,
                    config=DUMMY_CONFIG,
                )
                topic = await service.assign_topic(reply, state)
                await service.shutdown()

            self.assertEqual(topic.topic_id, "topic_1")
            self.assertEqual(state.message_topic_map["m2"], "topic_1")
            self.assertEqual(store.get_topic_messages(1, limit=5)[-1]["message_id"], "m2")


if __name__ == "__main__":
    unittest.main()
