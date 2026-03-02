from __future__ import annotations

"""
エントリポイント。

Usage:
    python -m src.main          # 常駐ポーリング
    python -m src.main --once   # 1回実行
"""

import argparse
import logging
import time

from .config import Config
from .journal_watcher import JournalWatcher
from .pattern_matcher import PatternMatcher
from .redmine_client import RedmineClient
from .state_store import StateStore
from .utils import setup_logging
from . import web_server

logger = logging.getLogger(__name__)


def build_components(cfg: Config) -> JournalWatcher:
    store = StateStore(cfg.db_path)
    redmine = RedmineClient(cfg.redmine_base_url, cfg.redmine_api_key)
    matcher = PatternMatcher(cfg.patterns_yaml)
    watcher = JournalWatcher(cfg=cfg, store=store, redmine=redmine, matcher=matcher)

    web_server.init(cfg, store, watcher._handle_box_work)

    return watcher


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
    web_server.start(cfg)
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
