from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

_SECRET_KEYS = re.compile(
    r"(token|key|password|secret|authorization|credential)", re.IGNORECASE
)


def mask_secret(value: str, visible: int = 4) -> str:
    """ログ出力用にシークレット文字列をマスクする。"""
    if not value:
        return "(empty)"
    if len(value) <= visible * 2:
        return "*" * len(value)
    return value[:visible] + "****" + value[-visible:]


def safe_log_dict(d: dict) -> dict:
    """センシティブなキーの値をマスクした辞書コピーを返す。"""
    return {
        k: mask_secret(str(v)) if _SECRET_KEYS.search(str(k)) else v
        for k, v in d.items()
    }


def setup_logging(level: str = "INFO") -> None:
    """ルートロガーの設定。"""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
