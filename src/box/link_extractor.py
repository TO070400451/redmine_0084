from __future__ import annotations

import re

# Box 共有リンクのパターン（共有リンク・フォルダ・ファイル）
_BOX_URL_RE = re.compile(
    r"https?://(?:[\w-]+\.)?box\.com/(?:s/[A-Za-z0-9_-]+|folder/\d+)",
    re.IGNORECASE,
)


def extract_box_links(text: str) -> list[str]:
    """テキストから Box 共有リンクを全て抽出する。"""
    return list(dict.fromkeys(_BOX_URL_RE.findall(text)))  # 順序保持の重複除去
