"""Fake implementations of BaseAgent and QQ senders for offline benchmarking.

Replaces simagentplg.BaseAgent via unittest.mock.patch so the benchmark
measures only pipeline overhead, not LLM inference latency.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Scenario configuration -- set by runner before each scenario
# ---------------------------------------------------------------------------

_scenario: dict[str, Any] = {}


def configure_scenario(**kwargs: Any) -> None:
    """Update the module-level scenario config for the current run."""
    _scenario.clear()
    _scenario.update(kwargs)


def _cfg(key: str, default: Any = None) -> Any:
    return _scenario.get(key, default)


# ---------------------------------------------------------------------------
# Fake BaseAgent -- replaces all three service agents
# ---------------------------------------------------------------------------


class FakeBaseAgent:
    """Deterministic replacement for simagentplg.BaseAgent.

    Dispatches based on ``agent_id``:
    - ``napcat_topic_classifier``   → tool dispatching (create/assign topic)
    - ``napcat_topic_summarizer``   → no-op (background tasks suppressed)
    - ``napcat_message_analyzer``   → returns pre-configured decision JSON
    - ``napcat_group_agent``        → tool dispatching (send_msg / skip_reply)
    """

    def __init__(
        self,
        config: Any = None,
        *,
        agent_id: str = "",
        system_prompt: str = "",
        handlers: list[Any] | None = None,
        enable_tools: bool = False,
        max_steps: int = 8,
    ) -> None:
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self._handlers = list(handlers or [])
        self._enable_tools = enable_tools
        self._max_steps = max_steps
        # The first handler is always the primary tool handler
        self.handler = self._handlers[0] if self._handlers else None

    # -- Public API (mirrors BaseAgent) ------------------------------------

    def reset(self) -> None:
        pass

    async def runtime(self, *, task: str) -> str:
        if self.agent_id == "napcat_topic_classifier":
            return await self._run_topic_classifier(task)
        if self.agent_id == "napcat_topic_summarizer":
            return "summarized"  # background tasks are suppressed
        if self.agent_id == "napcat_group_agent":
            return await self._run_reply_agent(task)
        return ""

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        tools: Any = None,
    ) -> dict[str, Any]:
        if self.agent_id == "napcat_message_analyzer":
            return dict(_cfg("decision_payload", {}))
        return {}

    async def chat_text(
        self,
        messages: list[dict[str, str]],
        *,
        tools: Any = None,
    ) -> Any:
        """Return a mock LLM response for text-only calls (used by group profile)."""
        # Return a simple object with a .content attribute
        return _FakeResult(content="mock profile text")

    async def shutdown(self) -> None:
        pass

    # -- Role-specific helpers ---------------------------------------------

    async def _run_topic_classifier(self, task: str) -> str:
        handler = self.handler
        if handler is None:
            return ""

        message = getattr(handler, "current_message", None)
        if message is None:
            return ""

        topic_action = _cfg("topic_action", "create_new")

        if topic_action == "assign_existing":
            # Simulate LLM listing recent topics then assigning to existing
            await handler.dispatch(
                "list_recent_topics",
                {"group_id": message.group_id, "limit": 10},
            )
            existing_id = _cfg("existing_topic_db_id", 1)
            await handler.dispatch(
                "assign_message_to_topic",
                {
                    "group_id": message.group_id,
                    "message_id": message.message_id,
                    "topic_id": existing_id,
                    "msg": message.text,
                },
            )
            return "assigned"

        # Default: create_new
        created = await handler.dispatch(
            "create_topic",
            {
                "group_id": message.group_id,
                "title": message.text[:24] or "新话题",
                "summary": message.text[:120] or "新话题",
            },
        )
        topic_id = int(created.data["id"])
        await handler.dispatch(
            "assign_message_to_topic",
            {
                "group_id": message.group_id,
                "message_id": message.message_id,
                "topic_id": topic_id,
                "msg": message.text,
            },
        )
        return "assigned"

    async def _run_reply_agent(self, task: str) -> str:
        handler = self.handler
        if handler is None:
            return ""

        reply_action = _cfg("reply_action", "send_msg")
        reply_text = _cfg("reply_text", "benchmark reply")

        if reply_action == "skip_reply":
            await handler.dispatch("skip_reply", {"reason": "benchmark silence"})
            return "skipped"

        if reply_action == "send_at_msg":
            user_id = _cfg("test_user_id", 2001)
            await handler.dispatch(
                "send_at_msg",
                {"user_id": user_id, "message": reply_text},
            )
            return "sent"

        # Default: send_msg
        await handler.dispatch("send_msg", {"message": reply_text})
        return "sent"


# ---------------------------------------------------------------------------
# Fake result object (mimics LLM text response)
# ---------------------------------------------------------------------------


class _FakeResult:
    __slots__ = ("content",)

    def __init__(self, content: str) -> None:
        self.content = content


# ---------------------------------------------------------------------------
# Fake Sender -- records QQ action calls without real network
# ---------------------------------------------------------------------------


class FakeSender:
    """Implements both NapcatActionSender and TopicActionSender protocols.

    Records all calls to ``self.calls`` instead of sending real QQ messages.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._await_calls: list[tuple[str, dict[str, Any]]] = []

    async def send_action(
        self,
        action: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append((action, dict(params)))
        return {"status": "ok"}

    async def send_action_and_wait(
        self,
        action: str,
        params: dict[str, Any],
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        self._await_calls.append((action, dict(params)))
        # Return empty message list for get_group_msg_history queries
        if action == "get_group_msg_history":
            return {"data": {"messages": []}}
        return {"status": "ok"}

    def clear(self) -> None:
        """Reset recorded calls between iterations."""
        self.calls.clear()
        self._await_calls.clear()
