from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS journal_events (
    journal_id      INTEGER PRIMARY KEY,
    issue_id        INTEGER NOT NULL,
    detected_at     TEXT NOT NULL,
    notified_at     TEXT,
    decision        TEXT DEFAULT 'pending',
    status          TEXT DEFAULT 'detected',
    matched_pattern TEXT,
    score           INTEGER,
    ticket_url      TEXT,
    box_links_json  TEXT,
    work_dir        TEXT,
    last_error      TEXT,
    issue_subject   TEXT,
    comment_excerpt TEXT
)
"""

_MIGRATE = [
    "ALTER TABLE journal_events ADD COLUMN issue_subject TEXT",
    "ALTER TABLE journal_events ADD COLUMN comment_excerpt TEXT",
]


class StateStore:
    """journal_id を主キーとした SQLite 状態管理。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(_CREATE_TABLE)
            conn.commit()
            for stmt in _MIGRATE:
                try:
                    conn.execute(stmt)
                    conn.commit()
                except sqlite3.OperationalError:
                    pass  # 列が既に存在する場合はスキップ
        logger.info("StateStore initialized: %s", db_path)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def exists(self, journal_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM journal_events WHERE journal_id = ?", (journal_id,)
            ).fetchone()
            return row is not None

    def insert_detected(
        self,
        journal_id: int,
        issue_id: int,
        detected_at: str,
        ticket_url: str,
        matched_pattern: Optional[str],
        score: Optional[int],
        box_links: list[str],
        issue_subject: Optional[str] = None,
        comment_excerpt: Optional[str] = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO journal_events
                  (journal_id, issue_id, detected_at, ticket_url,
                   matched_pattern, score, box_links_json, status, decision,
                   issue_subject, comment_excerpt)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'detected', 'pending', ?, ?)
                """,
                (
                    journal_id,
                    issue_id,
                    detected_at,
                    ticket_url,
                    matched_pattern,
                    score,
                    json.dumps(box_links, ensure_ascii=False),
                    issue_subject,
                    comment_excerpt,
                ),
            )
            conn.commit()
        logger.debug("Inserted journal_id=%d", journal_id)

    def get_dashboard_records(self) -> list[sqlite3.Row]:
        """ダッシュボード表示用：スコアありのレコードを新しい順で返す。"""
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT * FROM journal_events
                WHERE score IS NOT NULL
                ORDER BY detected_at DESC
                """
            ).fetchall()

    def mark_notified(self, journal_id: int, notified_at: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE journal_events SET status='notified', notified_at=? WHERE journal_id=?",
                (notified_at, journal_id),
            )
            conn.commit()

    def set_decision(self, journal_id: int, decision: str) -> None:
        """decision: 'work' | 'skip'"""
        with self._conn() as conn:
            conn.execute(
                "UPDATE journal_events SET decision=?, status='decided' WHERE journal_id=?",
                (decision, journal_id),
            )
            conn.commit()
        logger.info("Decision set: journal_id=%d decision=%s", journal_id, decision)

    def set_status(
        self,
        journal_id: int,
        status: str,
        error: Optional[str] = None,
        work_dir: Optional[str] = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE journal_events
                SET status=?, last_error=?, work_dir=COALESCE(?, work_dir)
                WHERE journal_id=?
                """,
                (status, error, work_dir, journal_id),
            )
            conn.commit()

    def get_decided_work(self) -> list[sqlite3.Row]:
        """decision='work' かつ status='decided' のレコードを返す。"""
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM journal_events WHERE decision='work' AND status='decided'"
            ).fetchall()

    def get_notified_pending(self) -> list[sqlite3.Row]:
        """Teams通知済み・未決定のレコードを返す。"""
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM journal_events WHERE status='notified' AND decision='pending'"
            ).fetchall()

    def get(self, journal_id: int) -> Optional[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM journal_events WHERE journal_id=?", (journal_id,)
            ).fetchone()
