from __future__ import annotations

"""Box フォルダの再帰探索とファイルダウンロード。"""

import logging
import re
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)
_API = "https://api.box.com/2.0"


@dataclass
class BoxFile:
    file_id: str
    name: str
    path: str  # ルートフォルダからの相対パス


def _get(path: str, token: str) -> dict:
    r = requests.get(f"{_API}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    return r.json()


def get_folder_name(folder_id: str, token: str) -> str:
    return _get(f"/folders/{folder_id}", token).get("name", "")


def find_files(
    folder_id: str,
    token: str,
    filename: str = "test_result.html",
    exclude_top: set[str] | None = None,
    _path: str = "",
    _depth: int = 0,
) -> list[BoxFile]:
    """指定ファイル名を再帰的に検索。exclude_top は最上位フォルダの除外リスト。"""
    if exclude_top is None:
        exclude_top = set()
    results: list[BoxFile] = []
    offset = 0
    while True:
        data = _get(f"/folders/{folder_id}/items?limit=1000&offset={offset}", token)
        entries = data.get("entries", [])
        for e in entries:
            name = e["name"]
            item_path = f"{_path}/{name}" if _path else name
            if e["type"] == "file" and name == filename:
                results.append(BoxFile(file_id=e["id"], name=name, path=item_path))
            elif e["type"] == "folder":
                if _depth == 0 and name in exclude_top:
                    logger.debug("Excluding folder: %s", name)
                    continue
                results.extend(
                    find_files(e["id"], token, filename, exclude_top, item_path, _depth + 1)
                )
        if len(entries) < 1000:
            break
        offset += 1000
    return results


def download_text(file_id: str, token: str) -> str:
    r = requests.get(
        f"{_API}/files/{file_id}/content",
        headers={"Authorization": f"Bearer {token}"},
        allow_redirects=True,
        timeout=60,
    )
    r.raise_for_status()
    return r.text


def resolve_folder_id(url: str, token: str) -> str:
    """Box URL（直接リンクまたは共有リンク）からフォルダ ID を取得する。"""
    m = re.search(r"box\.com/folder/(\d+)", url)
    if m:
        return m.group(1)
    # 共有リンク
    r = requests.get(
        f"{_API}/shared_items",
        headers={"Authorization": f"Bearer {token}", "BoxApi": f"shared_link={url}"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("type") != "folder":
        raise ValueError(f"Box リンクがフォルダではありません: {url}")
    return data["id"]
