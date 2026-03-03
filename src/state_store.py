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

_CREATE_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
)
"""

_MIGRATE = [
    "ALTER TABLE journal_events ADD COLUMN issue_subject TEXT",
    "ALTER TABLE journal_events ADD COLUMN comment_excerpt TEXT",
    "ALTER TABLE journal_events ADD COLUMN validation_status TEXT",
    "ALTER TABLE journal_events ADD COLUMN validation_defects_json TEXT",
    "ALTER TABLE journal_events ADD COLUMN project_name TEXT",
    "ALTER TABLE journal_events ADD COLUMN upload_status TEXT",
    "ALTER TABLE journal_events ADD COLUMN upload_results_json TEXT",
]


class StateStore:
    """journal_id を主キーとした SQLite 状態管理。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_SETTINGS)
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
        project_name: Optional[str] = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO journal_events
                  (journal_id, issue_id, detected_at, ticket_url,
                   matched_pattern, score, box_links_json, status, decision,
                   issue_subject, comment_excerpt, project_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'detected', 'pending', ?, ?, ?)
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
                    project_name,
                ),
            )
            conn.commit()
        logger.debug("Inserted journal_id=%d", journal_id)

    def get_dashboard_records(self, min_score: int = 80) -> list[sqlite3.Row]:
        """ダッシュボード表示用：チケットごとに最新1件、min_score 以上かつ dismissed でないレコードを返す。"""
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT * FROM journal_events
                WHERE score >= ? AND status != 'dismissed'
                  AND journal_id IN (
                    SELECT journal_id FROM journal_events
                    WHERE score >= ? AND status != 'dismissed'
                    GROUP BY issue_id
                    HAVING journal_id = MAX(journal_id)
                  )
                ORDER BY detected_at DESC
                """,
                (min_score, min_score),
            ).fetchall()

    def dismiss(self, journal_id: int) -> None:
        """単一レコードを dismissed にする（手動削除）。"""
        with self._conn() as conn:
            conn.execute(
                "UPDATE journal_events SET status='dismissed' WHERE journal_id=?",
                (journal_id,),
            )
            conn.commit()
        logger.info("Dismissed journal_id=%d", journal_id)

    def dismiss_issue(self, issue_id: int) -> int:
        """issue_id に紐づく全非 dismissed レコードを dismissed にする。
        処理中（decided/validating/downloading）のレコードは除外する。変更件数を返す。"""
        with self._conn() as conn:
            cur = conn.execute(
                """UPDATE journal_events SET status='dismissed'
                   WHERE issue_id=? AND status NOT IN ('dismissed', 'decided', 'validating', 'downloading')""",
                (issue_id,),
            )
            conn.commit()
            return cur.rowcount

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

    def set_validation_result(
        self,
        journal_id: int,
        ok: bool,
        defects: list[str],
    ) -> None:
        status = "validation_ok" if ok else "validation_ng"
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE journal_events
                SET validation_status=?, validation_defects_json=?
                WHERE journal_id=?
                """,
                (status, json.dumps(defects, ensure_ascii=False), journal_id),
            )
            conn.commit()
        logger.info("Validation result: journal_id=%d ok=%s defects=%d", journal_id, ok, len(defects))

    def get_decided_work(self) -> list[sqlite3.Row]:
        """decision='work' かつ status='decided' のレコードを返す。"""
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM journal_events WHERE decision='work' AND status='decided'"
            ).fetchall()

    def get_setting(self, key: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
            conn.commit()

    def set_upload_status(
        self,
        journal_id: int,
        status: str,
        results: dict | None = None,
    ) -> None:
        """upload_status を更新する。status: 'uploading'|'ok'|'rejected'|'failed'"""
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE journal_events
                SET upload_status=?, upload_results_json=?
                WHERE journal_id=?
                """,
                (
                    status,
                    json.dumps(results, ensure_ascii=False) if results is not None else None,
                    journal_id,
                ),
            )
            conn.commit()
        logger.info("Upload status: journal_id=%d status=%s", journal_id, status)

    def get_extracted_pending_upload(self) -> list[sqlite3.Row]:
        """status='extracted' かつ upload_status が未設定のレコードを返す。"""
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT * FROM journal_events
                WHERE status = 'extracted' AND upload_status IS NULL
                """
            ).fetchall()

    def get_active_issue_ids(self) -> list[int]:
        """dismissed/skip 以外の status を持つ issue_id 一覧を返す（重複なし）。"""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT issue_id FROM journal_events
                WHERE status NOT IN ('dismissed', 'decided')
                  AND decision != 'skip'
                """
            ).fetchall()
            return [r["issue_id"] for r in rows]

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
