import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
SIMAGENT_SRC = ROOT.parent / "SimAgentPlg" / "src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SIMAGENT_SRC))

from app.core.message import normalize_group_message
from app.core.topic_tracker import TopicTracker
from app.core.group_state import GroupState
from app.llm.napcat_actions import NapcatActionHandler
from app.core.decision import ReplyDecision
from app.core.decision_postcheck import post_check_decision
from app.core.context_builder import ContextBuilder


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def send_action(
        self,
        action: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append((action, params))
        return {"ok": True}


class NapcatAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_group_message_reads_segments(self) -> None:
        event = {
            "post_type": "message",
            "message_type": "group",
            "group_id": 100,
            "user_id": 200,
            "message_id": 300,
            "sender": {"nickname": "江义恒"},
            "message": [
                {"type": "reply", "data": {"id": "299"}},
                {"type": "at", "data": {"qq": "123"}},
                {"type": "text", "data": {"text": " 这个咋做"}},
            ],
        }

        message = normalize_group_message(event, bot_id=123, bot_name="蛋总")

        self.assertIsNotNone(message)
        assert message is not None
        self.assertEqual(message.group_id, 100)
        self.assertEqual(message.user_id, 200)
        self.assertEqual(message.text, "这个咋做")
        self.assertTrue(message.is_at_bot)
        self.assertEqual(message.reply_to, "299")

    async def test_send_msg_tool_uses_current_group(self) -> None:
        sender = FakeSender()
        handler = NapcatActionHandler(sender)
        handler.begin_turn(group_id=100)

        outcome = await handler.dispatch("send_msg", {"message": "**你好**"})

        self.assertTrue(outcome.should_exit)
        self.assertEqual(sender.calls[0][0], "send_group_msg")
        self.assertEqual(sender.calls[0][1]["group_id"], "100")
        self.assertEqual(sender.calls[0][1]["message"], "你好")
        self.assertFalse(sender.calls[0][1]["auto_escape"])

    async def test_send_at_msg_tool_uses_onebot_segments(self) -> None:
        sender = FakeSender()
        handler = NapcatActionHandler(sender)
        handler.begin_turn(group_id=100)

        outcome = await handler.dispatch(
            "send_at_msg",
            {"user_id": 200, "message": "看这一段"},
        )

        self.assertTrue(outcome.should_exit)
        params = sender.calls[0][1]
        self.assertEqual(params["group_id"], "100")
        self.assertEqual(
            params["message"],
            [
                {"type": "at", "data": {"qq": "200"}},
                {"type": "text", "data": {"text": " 看这一段"}},
            ],
        )

    def test_topic_tracker_maps_reply_to_existing_topic(self) -> None:
        tracker = TopicTracker()
        state = GroupState(group_id=100)
        first = normalize_group_message(
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
        assert first is not None
        state.add_message(first)
        topic = tracker.assign_topic(first, state)

        second = normalize_group_message(
            {
                "post_type": "message",
                "message_type": "group",
                "group_id": 100,
                "user_id": 201,
                "message_id": "m2",
                "sender": {"nickname": "B"},
                "message": [
                    {"type": "reply", "data": {"id": "m1"}},
                    {"type": "text", "data": {"text": "监听哪个端口"}},
                ],
            },
            bot_id=123,
            bot_name="蛋总",
        )
        assert second is not None
        state.add_message(second)
        reply_topic = tracker.assign_topic(second, state)

        self.assertEqual(reply_topic.topic_id, topic.topic_id)

    def test_reply_decision_from_payload_validates_fields(self) -> None:
        decision = ReplyDecision.from_payload(
            {
                "should_reply": True,
                "topic_id": "topic_1",
                "reply_intent": "ANSWER",
                "reply_style": "short_explain",
                "risk_level": "normal",
                "reply_target": "current_user",
                "confidence": 1.5,
                "reason": "asked directly",
            },
            fallback_topic_id="fallback",
        )

        self.assertTrue(decision.should_reply)
        self.assertEqual(decision.reply_intent, "ANSWER")
        self.assertEqual(decision.confidence, 1.0)

    def test_postcheck_silences_low_confidence_decision(self) -> None:
        message = normalize_group_message(
            {
                "post_type": "message",
                "message_type": "group",
                "group_id": 100,
                "user_id": 200,
                "message_id": "m1",
                "sender": {"nickname": "A"},
                "message": "随便说一句",
            },
            bot_id=123,
            bot_name="蛋总",
        )
        assert message is not None
        state = GroupState(group_id=100)
        topic = TopicTracker().assign_topic(message, state)
        decision = ReplyDecision(
            should_reply=True,
            topic_id=topic.topic_id,
            reply_intent="ANSWER",
            reply_style="short_reply",
            risk_level="normal",
            reply_target="topic",
            confidence=0.2,
            reason="weak signal",
        )

        checked = post_check_decision(
            decision,
            message=message,
            topic=topic,
            state=state,
        )

        self.assertFalse(checked.should_reply)
        self.assertEqual(checked.reply_intent, "SILENCE")

    def test_postcheck_converts_conflict_answer_to_cool_down(self) -> None:
        message = normalize_group_message(
            {
                "post_type": "message",
                "message_type": "group",
                "group_id": 100,
                "user_id": 200,
                "message_id": "m1",
                "sender": {"nickname": "A"},
                "message": [
                    {"type": "at", "data": {"qq": "123"}},
                    {"type": "text", "data": {"text": " 你说他是不是废物"}},
                ],
            },
            bot_id=123,
            bot_name="蛋总",
        )
        assert message is not None
        state = GroupState(group_id=100)
        topic = TopicTracker().assign_topic(message, state)
        decision = ReplyDecision(
            should_reply=True,
            topic_id=topic.topic_id,
            reply_intent="ANSWER",
            reply_style="short_explain",
            risk_level="conflict",
            reply_target="current_user",
            confidence=0.9,
            reason="direct mention",
        )

        checked = post_check_decision(
            decision,
            message=message,
            topic=topic,
            state=state,
        )

        self.assertTrue(checked.should_reply)
        self.assertEqual(checked.reply_intent, "COOL_DOWN")

    def test_action_context_includes_reply_decision(self) -> None:
        message = normalize_group_message(
            {
                "post_type": "message",
                "message_type": "group",
                "group_id": 100,
                "user_id": 200,
                "message_id": "m1",
                "sender": {"nickname": "A"},
                "message": "蛋总 这个怎么接",
            },
            bot_id=123,
            bot_name="蛋总",
        )
        assert message is not None
        state = GroupState(group_id=100)
        state.add_message(message)
        topic = TopicTracker().assign_topic(message, state)
        decision = ReplyDecision(
            should_reply=True,
            topic_id=topic.topic_id,
            reply_intent="ANSWER",
            reply_style="short_explain",
            risk_level="normal",
            reply_target="current_user",
            confidence=0.91,
            reason="asked bot",
        )

        task = ContextBuilder(bot_name="蛋总").build_action_task(
            message=message,
            topic=topic,
            state=state,
            decision=decision,
        )

        self.assertIn("【ReplyDecision】", task)
        self.assertIn("reply_intent: ANSWER", task)
        self.assertIn("send_at_msg", task)


if __name__ == "__main__":
    unittest.main()
