from __future__ import annotations

from pathlib import Path
import sqlite3
import time
from typing import Any

from app.core.message import BotMessage


class TopicStore:
    def __init__(self, db_path: str | Path = "data/topics.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # -- topics ----------------------------------------------------------------

    def list_recent_topics(
        self,
        group_id: int,
        *,
        limit: int = 10,
        ttl_seconds: int = 600,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cutoff = _now() - ttl_seconds
            conn.execute(
                "update topics set status = 'inactive' "
                "where group_id = ? and status = 'active' and updated_at < ?",
                (str(group_id), cutoff),
            )
            rows = conn.execute(
                """
                select id, group_id, topic_no, title, summary, history, status, created_at, updated_at
                from topics
                where group_id = ? and status = 'active'
                order by updated_at desc
                limit ?
                """,
                (str(group_id), limit),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def list_all_topics(
        self, group_id: int, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select id, topic_no, title, summary, status, updated_at
                from topics
                where group_id = ?
                order by updated_at desc
                limit ?
                """,
                (str(group_id), limit),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def delete_inactive_topics(self, group_id: int) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "delete from topics where group_id = ? and status = 'inactive'",
                (str(group_id),),
            )
            return cursor.rowcount

    def get_topic_by_no(self, group_id: int, topic_no: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select id, group_id, topic_no, title, summary, history, status, created_at, updated_at
                from topics
                where group_id = ? and topic_no = ?
                """,
                (str(group_id), topic_no),
            ).fetchone()
        return _row_dict(row) if row is not None else None

    def get_topic(self, topic_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select id, group_id, topic_no, title, summary, history, status, created_at, updated_at
                from topics
                where id = ?
                """,
                (topic_id,),
            ).fetchone()
        return _row_dict(row) if row is not None else None

    def create_topic(
        self,
        *,
        group_id: int,
        title: str,
        summary: str,
    ) -> dict[str, Any]:
        now = _now()
        title = title.strip()[:80] or "新话题"
        summary = summary.strip()[:500] or title
        with self._connect() as conn:
            next_no = self._next_topic_no(conn, group_id)
            cursor = conn.execute(
                """
                insert into topics(group_id, topic_no, title, summary, history, status, created_at, updated_at)
                values(?, ?, ?, ?, '', 'active', ?, ?)
                """,
                (str(group_id), next_no, title, summary, now, now),
            )
            topic_id = int(cursor.lastrowid)  # ty:ignore[invalid-argument-type]
        topic = self.get_topic(topic_id)
        assert topic is not None
        return topic

    def assign_message_to_topic(
        self,
        *,
        group_id: int,
        message: BotMessage,
        topic_id: int,
        text: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        msg_text = (text if text is not None else message.text).strip()
        with self._connect() as conn:
            conn.execute(
                "update topics set status = 'active', updated_at = ? where id = ?",
                (now, topic_id),
            )
            row = conn.execute(
                "select history from topics where id = ?",
                (topic_id,),
            ).fetchone()
            old_history = str(row["history"]) if row and row["history"] else ""
            parts = [p for p in old_history.split(" / ") if p]
            parts.append(f"{message.nickname}: {msg_text}")
            history = " / ".join(parts[-50:])[:2000]

            conn.execute(
                "update topics set history = ?, updated_at = ? where id = ?",
                (history, now, topic_id),
            )
        topic = self.get_topic(topic_id)
        assert topic is not None
        return topic

    def update_topic_summary(self, *, topic_id: int, summary: str) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                "update topics set summary = ? where id = ?",
                (summary.strip()[:500], topic_id),
            )
        topic = self.get_topic(topic_id)
        if topic is None:
            raise ValueError(f"topic {topic_id} does not exist")
        return topic

    # -- group profile ---------------------------------------------------------

    def get_group_profile(self, group_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "select group_id, profile, updated_at from group_profiles where group_id = ?",
                (str(group_id),),
            ).fetchone()
        return _row_dict(row) if row is not None else None

    def upsert_group_profile(self, group_id: int, profile: str) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into group_profiles(group_id, profile, updated_at)
                values(?, ?, ?)
                on conflict(group_id) do update set
                    profile = excluded.profile,
                    updated_at = excluded.updated_at
                """,
                (str(group_id), profile.strip()[:800], now),
            )

    def group_profile_stale(self, group_id: int, *, ttl_seconds: int = 86400) -> bool:
        profile = self.get_group_profile(group_id)
        if profile is None:
            return True
        return _now() - int(profile["updated_at"]) > ttl_seconds

    # -- internal -------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                create table if not exists topics (
                    id integer primary key autoincrement,
                    group_id text not null,
                    topic_no text not null,
                    title text not null,
                    summary text not null,
                    history text not null default '',
                    status text not null default 'active',
                    created_at integer not null,
                    updated_at integer not null,
                    unique(group_id, topic_no)
                );

                create table if not exists group_profiles (
                    group_id text primary key,
                    profile text not null default '',
                    updated_at integer not null
                );
                """)
            conn.execute(
                "create index if not exists idx_topics_group_updated "
                "on topics(group_id, status, updated_at)"
            )

    def _next_topic_no(self, conn: sqlite3.Connection, group_id: int) -> str:
        row = conn.execute(
            "select max(cast(replace(topic_no, 'topic_', '') as integer)) "
            "from topics where group_id = ?",
            (str(group_id),),
        ).fetchone()
        max_no = row[0] if row and row[0] is not None else 0
        return f"topic_{int(max_no) + 1}"


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _now() -> int:
    return int(time.time())
