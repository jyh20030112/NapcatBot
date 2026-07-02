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

    def list_recent_topics(
        self,
        group_id: int,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
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

    def get_topic_by_message(
        self,
        *,
        group_id: int,
        message_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select t.id, t.group_id, t.topic_no, t.title, t.summary, t.history, t.status,
                       t.created_at, t.updated_at
                from messages m
                join topics t on t.id = m.topic_id
                where m.group_id = ? and m.message_id = ?
                """,
                (str(group_id), message_id),
            ).fetchone()
        return _row_dict(row) if row is not None else None

    def get_topic_messages(
        self,
        topic_id: int,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select message_id, group_id, user_id, nickname, text, created_at
                from messages
                where topic_id = ?
                order by created_at desc, id desc
                limit ?
                """,
                (topic_id, limit),
            ).fetchall()
        return list(reversed([_row_dict(row) for row in rows]))

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
                """
                insert into messages(group_id, message_id, user_id, nickname, text, topic_id, created_at)
                values(?, ?, ?, ?, ?, ?, ?)
                on conflict(group_id, message_id) do update set
                    user_id = excluded.user_id,
                    nickname = excluded.nickname,
                    text = excluded.text,
                    topic_id = excluded.topic_id
                """,
                (
                    str(group_id),
                    message.message_id,
                    str(message.user_id),
                    message.nickname,
                    msg_text,
                    topic_id,
                    now,
                ),
            )
            history = self._recent_history(conn, topic_id)
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

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
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

                create table if not exists messages (
                    id integer primary key autoincrement,
                    group_id text not null,
                    message_id text not null,
                    user_id text,
                    nickname text,
                    text text not null,
                    topic_id integer not null references topics(id),
                    created_at integer not null,
                    unique(group_id, message_id)
                );

                create index if not exists idx_topics_group_updated
                    on topics(group_id, status, updated_at);
                create index if not exists idx_messages_topic_created
                    on messages(topic_id, created_at);
                """
            )
            _ensure_column(conn, "topics", "history", "text not null default ''")

    def _next_topic_no(self, conn: sqlite3.Connection, group_id: int) -> str:
        count = conn.execute(
            "select count(*) from topics where group_id = ?",
            (str(group_id),),
        ).fetchone()[0]
        return f"topic_{int(count) + 1}"

    def _recent_history(self, conn: sqlite3.Connection, topic_id: int) -> str:
        rows = conn.execute(
            """
            select text from messages
            where topic_id = ?
            order by created_at desc, id desc
            limit 50
            """,
            (topic_id,),
        ).fetchall()
        texts = [str(row["text"]) for row in reversed(rows) if row["text"]]
        return " / ".join(texts)[:2000] or ""


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    rows = conn.execute(f"pragma table_info({table})").fetchall()
    if any(str(row["name"]) == column for row in rows):
        return
    conn.execute(f"alter table {table} add column {column} {definition}")


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _now() -> int:
    return int(time.time())
