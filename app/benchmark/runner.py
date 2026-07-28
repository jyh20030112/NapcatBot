"""Benchmark runner — orchestrates fake services, timing, and data collection."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from simagentplg import ModelConfig

from app.core.group_state import GroupState
from app.core.message import normalize_group_message
from app.core.topic_store import TopicStore
from app.handlers.group_message_handler import GroupMessageHandler
from app.services.reply_agent_service import NapcatReplyAgent

from .fakes import (
    FakeBaseAgent,
    FakeSender,
    configure_scenario,
)
from .scenarios import Scenario, ALL_SCENARIOS
from .stats import compute_stage_stats, format_terminal, write_json_log

logger = logging.getLogger(__name__)

DUMMY_CONFIG = ModelConfig(
    model="benchmark-model",
    api_key="benchmark-key",
    base_url="http://benchmark.invalid/v1",
)


class BenchmarkRunner:
    """Runs pipeline latency benchmarks across configurable scenarios.

    Parameters
    ----------
    real_llm:
        When False (default), replaces BaseAgent with FakeBaseAgent —
        measures pure pipeline overhead with zero network calls.
        When True, uses the real simagentplg.BaseAgent with ModelConfig
        from your .env file — measures true end-to-end latency including
        LLM inference time (costs API credits!).
    """

    def __init__(
        self,
        *,
        iterations: int = 50,
        scenarios: list[str] | None = None,
        output_path: str = "data/benchmark_results.json",
        show_breakdown: bool = True,
        real_llm: bool = False,
    ) -> None:
        self.iterations = iterations
        self.scenario_names = scenarios or list(ALL_SCENARIOS)
        self.output_path = output_path
        self.show_breakdown = show_breakdown
        self.real_llm = real_llm

    async def run(self) -> None:
        """Execute all selected scenarios and emit statistics."""
        mode = "REAL LLM (from .env)" if self.real_llm else "MOCK (fake LLM, no API calls)"
        print(f"Benchmark mode: {mode}")

        all_stats: list[dict[str, Any]] = []
        raw_samples: list[dict[str, Any]] = []

        for name in self.scenario_names:
            scenario = ALL_SCENARIOS.get(name)
            if scenario is None:
                logger.warning("Unknown scenario %r — skipping", name)
                continue

            print(f"\nRunning scenario: {name}  ({self.iterations} iterations) ...")
            samples = await self._run_scenario(scenario)

            stats = compute_stage_stats(name, samples)
            all_stats.append(stats)

            for s in samples:
                s["scenario"] = name
            raw_samples.extend(samples)

        # -- Output ---------------------------------------------------------
        report = format_terminal(all_stats, show_breakdown=self.show_breakdown)
        print(f"\n{report}")

        write_json_log(all_stats, self.output_path, raw_samples=raw_samples)
        print(f"JSON log written to: {self.output_path}")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run_scenario(self, scenario: Scenario) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []

        for run_idx in range(self.iterations):
            timing = await self._run_single_iteration(scenario, run_idx)
            samples.append(timing)

            if (run_idx + 1) % 10 == 0:
                print(f"  ... {run_idx + 1}/{self.iterations}")

        return samples

    async def _run_single_iteration(
        self,
        scenario: Scenario,
        run_index: int,
    ) -> dict[str, Any]:
        """Create a fresh handler, seed state, then run one timed test event."""

        _ensure_env(real=self.real_llm)

        # Each iteration gets a clean SQLite database.
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "topics.sqlite3"
            os.environ["TOPIC_DB_PATH"] = str(db_path)

            fake_sender = FakeSender()

            # -- Construct handler (patched or real) -------------------------
            if self.real_llm:
                # Real LLM calls — reads ModelConfig from .env.
                # Patch McpToolHandler.startup so BaseAgent.startup() (called
                # during NapcatReplyAgent.__init__) doesn't launch a real
                # Playwright browser.
                from simagentplg.handlers.mcp import McpToolHandler

                with patch.object(McpToolHandler, "startup", _async_noop):
                    reply_agent = NapcatReplyAgent(
                        sender=fake_sender,
                        bot_name=scenario.bot_name,
                        bot_id=scenario.bot_id,
                        owner_name=scenario.owner_name,
                        owner_id=scenario.owner_id,
                        config=None,  # triggers ModelConfig.from_env()
                    )
                handler = GroupMessageHandler(
                    bot_id=scenario.bot_id,
                    bot_name=scenario.bot_name,
                    agent=reply_agent,
                    hide=False,
                    owner_name=scenario.owner_name,
                    owner_id=scenario.owner_id,
                    topic_sender=fake_sender,
                )
            else:
                # Fake LLM — patch BaseAgent with deterministic fakes
                with (
                    patch("app.services.topic_agent_service.BaseAgent", FakeBaseAgent),
                    patch(
                        "app.services.decision_agent_service.BaseAgent",
                        FakeBaseAgent,
                    ),
                    patch(
                        "app.services.reply_agent_service.BaseAgent",
                        FakeBaseAgent,
                    ),
                ):
                    reply_agent = NapcatReplyAgent(
                        sender=fake_sender,
                        bot_name=scenario.bot_name,
                        bot_id=scenario.bot_id,
                        owner_name=scenario.owner_name,
                        owner_id=scenario.owner_id,
                        config=DUMMY_CONFIG,
                    )
                    handler = GroupMessageHandler(
                        bot_id=scenario.bot_id,
                        bot_name=scenario.bot_name,
                        agent=reply_agent,
                        hide=False,
                        owner_name=scenario.owner_name,
                        owner_id=scenario.owner_id,
                        topic_sender=fake_sender,
                    )

            # -- Suppress background tasks & MCP (before any handle_event) ---
            handler.topic_agent._schedule_summary_refresh = lambda tid: None  # type: ignore[method-assign]
            handler.topic_agent._schedule_profile_refresh = lambda gid: None  # type: ignore[method-assign]
            # Mark MCP as already-started so:
            #  1. McpToolHandler.startup() short-circuits (already patched
            #     to noop during construction for real-LLM, but this belt-
            #     and-suspenders covers all paths)
            #  2. _ensure_mcp_started() skips calling startup again
            handler.agent.mcp_handler._started = True
            handler.agent._mcp_started = True

            # -- Seed state directly (bypass LLM pipeline for setup) ---------
            store = handler.topic_agent.store
            group_state = _ensure_group_state(handler, scenario.group_id)

            for idx, seed_event in enumerate(scenario.seed_events):
                seed_msg = normalize_group_message(
                    seed_event,
                    bot_id=scenario.bot_id,
                    bot_name=scenario.bot_name,
                )
                if seed_msg is None:
                    continue

                # Create a topic for this seed message
                topic_row = store.create_topic(
                    group_id=scenario.group_id,
                    title=seed_msg.text[:24] or "种子话题",
                    summary=seed_msg.text[:120] or "种子话题",
                )
                store.assign_message_to_topic(
                    group_id=scenario.group_id,
                    message=seed_msg,
                    topic_id=int(topic_row["id"]),
                )

                # Sync into in-memory GroupState so the fast-path & context builder work
                _sync_seed_to_state(topic_row, seed_msg, group_state)
                group_state.add_message(seed_msg)

            # -- Configure fake agent behaviour (skip for real LLM) ----------
            if not self.real_llm:
                configure_scenario(
                    topic_action=scenario.topic_action,
                    decision_payload=scenario.decision_payload,
                    reply_action=scenario.reply_action,
                    reply_text=scenario.reply_text,
                    test_user_id=scenario.test_event.get("user_id", 2001),
                    existing_topic_db_id=1,
                )
            fake_sender.clear()

            # -- Install timing wrappers ------------------------------------
            _orig_assign = handler.topic_agent.assign_topic
            _orig_analyze = handler.decision_service.analyze
            _orig_handle = handler.agent.handle_message

            timings: dict[str, float] = {}

            async def _timed_assign(*args: Any, **kwargs: Any) -> Any:
                t0 = time.monotonic()
                try:
                    return await _orig_assign(*args, **kwargs)
                finally:
                    timings["topic_ms"] = (time.monotonic() - t0) * 1000

            async def _timed_analyze(*args: Any, **kwargs: Any) -> Any:
                t0 = time.monotonic()
                try:
                    return await _orig_analyze(*args, **kwargs)
                finally:
                    timings["analyze_ms"] = (time.monotonic() - t0) * 1000

            async def _timed_handle(*args: Any, **kwargs: Any) -> Any:
                t0 = time.monotonic()
                try:
                    return await _orig_handle(*args, **kwargs)
                finally:
                    timings["reply_ms"] = (time.monotonic() - t0) * 1000

            handler.topic_agent.assign_topic = _timed_assign  # type: ignore[method-assign]
            handler.decision_service.analyze = _timed_analyze  # type: ignore[method-assign]
            handler.agent.handle_message = _timed_handle  # type: ignore[method-assign]

            # -- Run test event (timed) -------------------------------------
            t_total = time.monotonic()
            await handler.handle_event(scenario.test_event)
            timings["total_ms"] = (time.monotonic() - t_total) * 1000

            # Restore originals
            handler.topic_agent.assign_topic = _orig_assign  # type: ignore[method-assign]
            handler.decision_service.analyze = _orig_analyze  # type: ignore[method-assign]
            handler.agent.handle_message = _orig_handle  # type: ignore[method-assign]

            # -- Collect results --------------------------------------------
            topic_ms = timings.get("topic_ms", 0.0)
            analyze_ms = timings.get("analyze_ms", 0.0)
            reply_ms = timings.get("reply_ms", 0.0)

            action = "none"
            if fake_sender.calls:
                action = fake_sender.calls[-1][0]

            # Shut down services cleanly
            await handler.shutdown()

        return {
            "iteration": run_index,
            "total_ms": round(timings["total_ms"], 4),
            "stages": {
                "normalize_overhead_ms": round(
                    timings["total_ms"] - topic_ms - analyze_ms - reply_ms, 4
                ),
                "topic_ms": round(topic_ms, 4),
                "analyze_ms": round(analyze_ms, 4),
                "reply_ms": round(reply_ms, 4),
            },
            "action": action,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_group_state(handler: GroupMessageHandler, group_id: int) -> GroupState:
    """Get or create the GroupState for a group_id."""
    if group_id not in handler.group_states:
        handler.group_states[group_id] = GroupState(group_id=group_id)
    return handler.group_states[group_id]


def _sync_seed_to_state(
    topic_row: dict[str, Any],
    message: Any,  # BotMessage
    state: GroupState,
) -> None:
    """Mirror a TopicStore topic into the in-memory GroupState.

    This replicates what ``_sync_topic_state`` in topic_agent_service.py does,
    so the handler's fast-path (reply_to) and context builder work correctly.
    """
    from app.core.reply import detect_risk

    topic_id = str(topic_row["topic_no"])
    title = str(topic_row["title"])
    summary = str(topic_row["summary"])
    updated_at = float(topic_row["updated_at"])

    if topic_id in state.topics:
        topic = state.topics[topic_id]
        topic.title = title
        topic.summary = summary
        topic.last_active_at = updated_at
    else:
        from app.core.group_state import TopicState

        topic = TopicState(
            topic_id=topic_id,
            title=title,
            summary=summary,
            last_active_at=updated_at,
        )
        state.topics[topic_id] = topic

    state.record_topic_message(topic, message)
    recent_text = " / ".join(item.text for item in topic.last_messages[-20:])
    topic.risk_level = detect_risk(recent_text)


async def _async_noop(*args: Any, **kwargs: Any) -> None:
    return None


def _ensure_env(*, real: bool = False) -> None:
    """Set fallback env vars for fake mode; in real mode .env should provide them."""
    if real:
        # Load .env (dotenv will pick up the real API keys)
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=".env", override=False)
        return
    os.environ.setdefault("MODEL_API_KEY", "benchmark-key")
    os.environ.setdefault("MODEL_URL", "http://localhost:8080")
    os.environ.setdefault("BASE_MODEL", "benchmark-model")
