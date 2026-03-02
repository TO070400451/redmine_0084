from __future__ import annotations

"""
Box フォルダ内のファイルを個別にダウンロードするユーティリティ。

- download_bts_folder : フォルダ直下のファイル（ZIP等）をそのままDL
- download_from_ancestor: N階層上の祖先フォルダを起点に再帰DL
"""

import logging
from pathlib import Path
from typing import Any

import requests

_BOX_API_BASE = "https://api.box.com/2.0"
logger = logging.getLogger(__name__)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_folder_info(folder_id: str, token: str) -> dict[str, Any]:
    """フォルダ情報（id, name, parent）を返す。"""
    resp = requests.get(
        f"{_BOX_API_BASE}/folders/{folder_id}",
        headers=_headers(token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def list_folder_items(folder_id: str, token: str) -> list[dict[str, Any]]:
    """フォルダ内の全アイテムを返す（ページング対応）。"""
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        resp = requests.get(
            f"{_BOX_API_BASE}/folders/{folder_id}/items",
            headers=_headers(token),
            params={"fields": "id,name,type,size", "offset": offset, "limit": 1000},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        entries: list[dict[str, Any]] = data.get("entries", [])
        items.extend(entries)
        offset += len(entries)
        if offset >= data.get("total_count", 0) or not entries:
            break
    return items


def download_file(file_id: str, file_name: str, token: str, dest_path: Path) -> None:
    """単一ファイルを dest_path にダウンロードする。"""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(
        f"{_BOX_API_BASE}/files/{file_id}/content",
        headers=_headers(token),
        stream=True,
        timeout=300,
        allow_redirects=True,
    )
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
    logger.info("Downloaded: %s (%d bytes)", dest_path.name, dest_path.stat().st_size)


def _download_recursive(folder_id: str, token: str, dest_dir: Path) -> None:
    """フォルダを再帰的にダウンロードする。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for item in list_folder_items(folder_id, token):
        name: str = item["name"]
        if item["type"] == "file":
            download_file(item["id"], name, token, dest_dir / name)
        elif item["type"] == "folder":
            _download_recursive(item["id"], token, dest_dir / name)


def navigate_to_ancestor(folder_id: str, token: str, levels: int) -> dict[str, Any]:
    """folder_id から levels 階層上の祖先フォルダ情報を返す。"""
    info = get_folder_info(folder_id, token)
    for _ in range(levels):
        parent = info.get("parent") or {}
        if not parent.get("id") or parent["id"] == "0":
            logger.warning("Reached root before completing %d levels up", levels)
            break
        info = get_folder_info(parent["id"], token)
    return info


def download_bts_folder(folder_id: str, token: str, dest_dir: Path) -> None:
    """BTSフォルダ直下のファイル（ZIP等）をそのまま dest_dir にダウンロードする。"""
    items = list_folder_items(folder_id, token)
    files = [i for i in items if i["type"] == "file"]
    if not files:
        logger.warning("No files found in BTS folder id=%s", folder_id)
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        logger.info("BTS file: %s", f["name"])
        download_file(f["id"], f["name"], token, dest_dir / f["name"])


def download_from_ancestor(
    folder_id: str, token: str, dest_dir: Path, parent_levels: int = 2
) -> None:
    """
    folder_id から parent_levels 階層上の祖先フォルダを起点に
    フォルダ構造を保ちながら dest_dir 以下にダウンロードする。
    """
    ancestor = navigate_to_ancestor(folder_id, token, parent_levels)
    top_name: str = ancestor["name"]
    top_id: str = ancestor["id"]
    logger.info("GTS top folder: %s (id=%s)", top_name, top_id)
    _download_recursive(top_id, token, dest_dir / top_name)
