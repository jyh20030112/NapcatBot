import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class ChatStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def record_message(
        self,
        *,
        direction: str,
        message_type: str,
        session_id: str,
        user_id: str,
        group_id: str | None,
        sender_name: str,
        text: str,
        raw_message: Any = None,
    ) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (
                    created_at,
                    direction,
                    message_type,
                    session_id,
                    group_id,
                    user_id,
                    sender_name,
                    text,
                    raw_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(timespec="seconds"),
                    direction,
                    message_type,
                    session_id,
                    group_id,
                    user_id,
                    sender_name,
                    text,
                    self._serialize(raw_message),
                ),
            )

    def recent_messages(
        self,
        *,
        session_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    created_at,
                    direction,
                    message_type,
                    session_id,
                    group_id,
                    user_id,
                    sender_name,
                    text
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def _init_db(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    group_id TEXT,
                    user_id TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    raw_message TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
                ON chat_messages (session_id, created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_messages_group_created
                ON chat_messages (group_id, created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_messages_user_created
                ON chat_messages (user_id, created_at)
                """
            )

    @staticmethod
    def _serialize(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)
