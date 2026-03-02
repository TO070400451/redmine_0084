from __future__ import annotations

"""
Redmine からポーリングして未処理 journal を検出し、
パターン判定・Teams 通知・Box 処理まで一貫して実行する。
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from .box.link_extractor import extract_box_links
from .box.shared_item import SharedItemResolver
from .box.zip_downloader import ZipDownloader
from .box.token_manager import TokenManager
from .box.validator import validate as validate_box
from .box.waiver_parser import extract_waiver_tests
from . import dashboard, win_notifier
from .extractor import write_meta
from .pattern_matcher import PatternMatcher
from .redmine_client import RedmineClient
from .state_store import StateStore

logger = logging.getLogger(__name__)

_DISMISS_USER = "大橋翼"
_DISMISS_PHRASES = [
    "BTS/GtsEdiHostTestCases を Google社サーバーにアップロード致しました",
    "以下に承認通知を置きました",
]


class JournalWatcher:
    """メインのポーリング・処理ループ。"""

    def __init__(
        self,
        cfg: Any,
        store: StateStore,
        redmine: RedmineClient,
        matcher: PatternMatcher,
    ) -> None:
        self._cfg = cfg
        self._store = store
        self._redmine = redmine
        self._matcher = matcher
        self._token_mgr: Optional[TokenManager] = (
            TokenManager(
                client_id=cfg.box_client_id,
                client_secret=cfg.box_client_secret,
                access_token=cfg.box_access_token,
                refresh_token=cfg.box_refresh_token,
            )
            if cfg.box_client_id and cfg.box_refresh_token
            else None
        )

    def _box_token(self) -> str:
        """有効な Box アクセストークンを返す。TokenManager がなければ設定値をそのまま使う。"""
        if self._token_mgr:
            return self._token_mgr.access_token
        return self._cfg.box_access_token

    def _box_token_refresh(self) -> str:
        """トークンをリフレッシュして返す。TokenManager がない場合はそのまま返す。"""
        if self._token_mgr:
            return self._token_mgr.refresh()
        return self._cfg.box_access_token

    # ------------------------------------------------------------------
    # Public: 1回の処理サイクル
    # ------------------------------------------------------------------

    def run_once(self) -> None:
        """1 回のポーリングサイクルを実行する。"""
        logger.info("--- Poll cycle start ---")
        self._detect_and_notify()
        self._process_work_decisions()
        dashboard.generate(self._store, self._cfg.dashboard_path)
        logger.info("--- Poll cycle end ---")

    # ------------------------------------------------------------------
    # Step 1: 新規 journal の検出と通知
    # ------------------------------------------------------------------

    def _detect_and_notify(self) -> None:
        try:
            issues = self._redmine.get_updated_issues(
                self._cfg.redmine_project_id,
                limit=self._cfg.issue_fetch_limit,
            )
        except Exception as exc:
            logger.error("Failed to fetch issues: %s", exc)
            return

        for issue_summary in issues:
            issue_id: int = issue_summary["id"]
            try:
                issue = self._redmine.get_issue_with_journals(issue_id)
            except Exception as exc:
                logger.error("Failed to fetch issue %d: %s", issue_id, exc)
                continue

            journals: list[dict[str, Any]] = issue.get("journals", [])

            # 完了コメント確認 → 自動 dismiss
            if self._should_dismiss(journals):
                dismissed = self._store.dismiss_issue(issue_id)
                if dismissed:
                    logger.info(
                        "Auto-dismissed issue_id=%d (%d records)", issue_id, dismissed
                    )

            for journal in journals:
                self._process_journal(issue, journal)

    def _should_dismiss(self, journals: list[dict[str, Any]]) -> bool:
        """大橋翼 による完了フレーズを含む journal があれば True を返す。"""
        for journal in journals:
            user_name = journal.get("user", {}).get("name", "")
            if _DISMISS_USER not in user_name:
                continue
            notes = journal.get("notes", "") or ""
            if any(phrase in notes for phrase in _DISMISS_PHRASES):
                return True
        return False

    def _process_journal(
        self, issue: dict[str, Any], journal: dict[str, Any]
    ) -> None:
        journal_id: int = journal["id"]

        if self._store.exists(journal_id):
            return  # 冪等性：既処理スキップ

        issue_id: int = issue["id"]
        ticket_url = f"{self._cfg.redmine_base_url}/issues/{issue_id}"
        detected_at = datetime.now(timezone.utc).isoformat()

        # スコアリング対象テキスト収集
        notes: str = journal.get("notes", "") or ""
        details_text = _details_to_text(journal.get("details", []))
        subject: str = issue.get("subject", "") or ""
        description: str = issue.get("description", "") or ""
        full_text = "\n".join([notes, details_text, subject, description])

        # Box リンク抽出
        box_links = extract_box_links(full_text)
        has_box = bool(box_links)

        # パターン判定
        results = self._matcher.match(
            texts=[notes, details_text, subject, description],
            has_box_link=has_box,
        )

        best = results[0] if results else None
        comment_excerpt = notes[:200] if notes else details_text[:200]

        self._store.insert_detected(
            journal_id=journal_id,
            issue_id=issue_id,
            detected_at=detected_at,
            ticket_url=ticket_url,
            matched_pattern=best.pattern_id if best else None,
            score=best.score if best else None,
            box_links=box_links,
            issue_subject=subject,
            comment_excerpt=comment_excerpt,
        )

        if best is None:
            logger.debug(
                "journal_id=%d score below threshold, no notification", journal_id
            )
            self._store.set_decision(journal_id, "skip")
            return

        # Windows トースト通知
        win_notifier.notify(
            title=f"Redmine #{issue_id}",
            body=subject or comment_excerpt or "(コメントなし)",
        )
        notified_at = datetime.now(timezone.utc).isoformat()
        self._store.mark_notified(journal_id, notified_at)

        # ダッシュボード更新
        dashboard.generate(self._store, self._cfg.dashboard_path)

    # ------------------------------------------------------------------
    # Step 2: work 決定済みの Box 処理
    # ------------------------------------------------------------------

    def _process_work_decisions(self) -> None:
        rows = self._store.get_decided_work()
        for row in rows:
            self._handle_box_work(row)

    def _handle_box_work(self, row: Any) -> None:
        journal_id: int = row["journal_id"]
        issue_id: int = row["issue_id"]
        ticket_url: str = row["ticket_url"] or ""
        matched_pattern: Optional[str] = row["matched_pattern"]
        score: Optional[int] = row["score"]
        box_links: list[str] = json.loads(row["box_links_json"] or "[]")

        logger.info("Processing Box work: journal_id=%d", journal_id)

        # --- Waiver リスト取得 ---
        waiver_tests: set[str] = set()
        try:
            issue = self._redmine.get_issue_with_journals(issue_id)
            all_notes = "\n".join(
                j.get("notes", "") for j in issue.get("journals", [])
            )
            waiver_tests = extract_waiver_tests(all_notes)
            if waiver_tests:
                logger.info(
                    "Waivers found for issue %d: %d tests", issue_id, len(waiver_tests)
                )
        except Exception as exc:
            logger.warning("Failed to fetch waivers for issue %d: %s", issue_id, exc)

        # --- バリデーション（パターンが要求する場合のみ）---
        shared_link = box_links[0] if box_links else ""
        should_validate = self._matcher.requires_box_validation(matched_pattern or "")
        if should_validate and shared_link:
            self._store.set_status(journal_id, "validating")
            try:
                val = validate_box(shared_link, self._box_token(), waiver_tests=waiver_tests)
            except Exception as e:
                logger.error("Validation error journal_id=%d: %s", journal_id, e)
                val_ok = False
                defects = [f"バリデーション実行エラー: {e}"]
            else:
                val_ok = val.ok
                defects = val.defects
            self._store.set_validation_result(journal_id, val_ok, defects)
            if not val_ok:
                logger.warning(
                    "Validation failed journal_id=%d: %d defects", journal_id, len(defects)
                )
                self._store.set_status(
                    journal_id, "failed",
                    error="瑕疵あり: " + " / ".join(d.split("\n")[0] for d in defects),
                )
                return
        elif not should_validate:
            logger.info("Box validation skipped for pattern=%s journal_id=%d", matched_pattern, journal_id)

        self._store.set_status(journal_id, "downloading")

        # 作業ディレクトリ作成
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        work_dir = (
            Path(self._cfg.work_root)
            / "tickets"
            / str(issue_id)
            / f"{ts}_journal_{journal_id}"
        )
        raw_dir = work_dir / "01_raw"
        extract_dir = work_dir / "02_extract"
        raw_dir.mkdir(parents=True, exist_ok=True)

        # Box リンクが複数の場合は最初のものを使用
        box_item_type: Optional[str] = None
        box_item_id: Optional[str] = None
        download_status = "skipped"
        extract_status = "skipped"
        error_summary: Optional[str] = None

        if not box_links:
            logger.warning("No Box links for journal_id=%d", journal_id)
            self._store.set_status(
                journal_id,
                "failed",
                error="No Box links found",
                work_dir=str(work_dir),
            )
            write_meta(
                work_dir, issue_id, journal_id, ticket_url,
                matched_pattern, score, [], box_links,
                None, None, "no_links", "skipped",
            )
            return

        shared_link = box_links[0]

        try:
            token = self._box_token()
            try:
                resolver = SharedItemResolver(token, self._cfg.box_shared_link_password)
                item_info = resolver.resolve(shared_link)
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 401:
                    token = self._box_token_refresh()
                    resolver = SharedItemResolver(token, self._cfg.box_shared_link_password)
                    item_info = resolver.resolve(shared_link)
                else:
                    raise

            box_item_type = item_info["type"]
            box_item_id = item_info["id"]

            # 直接URL（/folder/ID, /file/ID）では BoxApi ヘッダー不要
            dl_shared_link = "" if item_info.get("is_direct") else shared_link
            downloader = ZipDownloader(token, dl_shared_link, self._cfg.box_shared_link_password)
            zip_name = f"download{'.' + box_item_info_ext(box_item_type)}"
            zip_path = downloader.download(
                item_type=box_item_type,
                item_id=box_item_id,
                dest_path=raw_dir,
                download_file_name=zip_name,
            )
            download_status = "ok"
        except Exception as exc:
            logger.error("Box download failed for journal_id=%d: %s", journal_id, exc)
            error_summary = str(exc)
            download_status = "failed"
            self._store.set_status(
                journal_id, "failed", error=error_summary, work_dir=str(work_dir)
            )
            write_meta(
                work_dir, issue_id, journal_id, ticket_url,
                matched_pattern, score, [], box_links,
                box_item_type, box_item_id,
                download_status, extract_status, error_summary,
            )
            return

        # 解凍は行わない（ダウンロードのみ）
        extract_status = "ok"

        final_status = "extracted" if extract_status == "ok" else "failed"
        self._store.set_status(
            journal_id, final_status, error=error_summary, work_dir=str(work_dir)
        )
        write_meta(
            work_dir, issue_id, journal_id, ticket_url,
            matched_pattern, score, [], box_links,
            box_item_type, box_item_id,
            download_status, extract_status, error_summary,
        )
        logger.info(
            "Box work done: journal_id=%d status=%s work_dir=%s",
            journal_id,
            final_status,
            work_dir,
        )


def _details_to_text(details: list[dict[str, Any]]) -> str:
    """journal.details をテキスト化する。"""
    parts: list[str] = []
    for d in details:
        prop = d.get("name", "")
        old_val = d.get("old_value", "") or ""
        new_val = d.get("new_value", "") or ""
        parts.append(f"{prop}: {old_val} -> {new_val}")
    return "\n".join(parts)


def box_item_info_ext(item_type: str) -> str:
    return "zip" if item_type == "folder" else "bin"
