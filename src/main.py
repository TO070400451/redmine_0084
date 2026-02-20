from __future__ import annotations

"""
エントリポイント。

Usage:
    python -m src.main          # 常駐ポーリング
    python -m src.main --once   # 1回実行
"""

import argparse
import logging
import sys
import threading
import time

import uvicorn

from .config import Config
from .journal_watcher import JournalWatcher
from .pattern_matcher import PatternMatcher
from .redmine_client import RedmineClient
from .state_store import StateStore
from .teams.bot_server import app as bot_app, set_state_store
from .teams.notifier import TeamsNotifier
from .utils import setup_logging

logger = logging.getLogger(__name__)


def build_components(cfg: Config) -> JournalWatcher:
    store = StateStore(cfg.db_path)
    redmine = RedmineClient(cfg.redmine_base_url, cfg.redmine_api_key)
    matcher = PatternMatcher(cfg.patterns_yaml)
    notifier = TeamsNotifier(cfg)

    # Bot サーバーに StateStore を注入
    set_state_store(store)

    return JournalWatcher(
        cfg=cfg,
        store=store,
        redmine=redmine,
        matcher=matcher,
        notifier=notifier,
    )


def start_bot_server(cfg: Config) -> None:
    """Bot サーバーを別スレッドで起動する（bot モード時のみ）。"""
    if cfg.teams_mode != "bot":
        return

    def _run() -> None:
        uvicorn.run(
            bot_app,
            host=cfg.bot_server_host,
            port=cfg.bot_server_port,
            log_level="warning",
        )

    thread = threading.Thread(target=_run, daemon=True, name="bot-server")
    thread.start()
    logger.info(
        "Bot server started on %s:%d", cfg.bot_server_host, cfg.bot_server_port
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Redmine journals → Teams → Box 自動化ツール"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="1 回だけ実行して終了する",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="ログレベル (デフォルト: INFO)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)

    cfg = Config()
    logger.info(
        "Starting: mode=%s teams_mode=%s poll_interval=%ds",
        "once" if args.once else "daemon",
        cfg.teams_mode,
        cfg.poll_interval_seconds,
    )

    watcher = build_components(cfg)

    if args.once:
        watcher.run_once()
        logger.info("--once completed. Exiting.")
        return

    # 常駐モード
    start_bot_server(cfg)

    try:
        while True:
            try:
                watcher.run_once()
            except Exception as exc:
                logger.error("Unexpected error in poll cycle: %s", exc, exc_info=True)
            logger.info(
                "Sleeping %d seconds until next poll...", cfg.poll_interval_seconds
            )
            time.sleep(cfg.poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Interrupted. Shutting down.")


if __name__ == "__main__":
    main()
