from __future__ import annotations

"""
Box からファイルまたはフォルダを ZIP 形式でダウンロードする。

- file  → POST /files/<id>/content（ダウンロードURL取得）
- folder → POST /zip_downloads（ZIP 作成 → download_url で取得）
"""

import logging
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

_BOX_API_BASE = "https://api.box.com/2.0"
_BOX_DL_BASE = "https://dl.boxcloud.com/2.0"


class ZipDownloader:
    """Box API を用いて file/folder を ZIP でダウンロードする。"""

    def __init__(self, access_token: str, shared_link: str = "", shared_link_password: str = "") -> None:
        self._token = access_token
        self._shared_link = shared_link
        self._shared_link_password = shared_link_password

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Authorization": f"Bearer {self._token}"}
        if self._shared_link:
            box_api = f"shared_link={self._shared_link}"
            if self._shared_link_password:
                box_api += f"&shared_link_password={self._shared_link_password}"
            headers["BoxApi"] = box_api
        return headers

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def download(
        self,
        item_type: str,
        item_id: str,
        dest_path: Path,
        download_file_name: str = "download.zip",
    ) -> Path:
        """
        item_type='file'  → ファイルダウンロード（ZIP ではなく元ファイルのまま）
        item_type='folder' → ZIP アーカイブを作成してダウンロード

        Returns:
            保存したファイルの Path
        """
        dest_path.mkdir(parents=True, exist_ok=True)

        if item_type == "file":
            return self._download_file(item_id, dest_path, download_file_name)
        elif item_type == "folder":
            return self._download_folder_as_zip(item_id, dest_path, download_file_name)
        else:
            raise ValueError(f"Unknown item_type: {item_type}")

    # ------------------------------------------------------------------
    # File download
    # ------------------------------------------------------------------

    def _download_file(
        self, file_id: str, dest_dir: Path, filename: str
    ) -> Path:
        """Box ファイルを直接ダウンロードする。"""
        url = f"{_BOX_API_BASE}/files/{file_id}/content"
        logger.info("Downloading file: id=%s", file_id)
        resp = requests.get(
            url, headers=self._auth_headers(), stream=True, timeout=60
        )
        resp.raise_for_status()

        # Content-Disposition からファイル名を取ろうとする（任意）
        cd = resp.headers.get("Content-Disposition", "")
        if 'filename="' in cd:
            fn_part = cd.split('filename="')[1].split('"')[0]
            if fn_part:
                filename = fn_part

        out_path = dest_dir / filename
        _stream_to_file(resp, out_path)
        logger.info("File downloaded: %s (%d bytes)", out_path, out_path.stat().st_size)
        return out_path

    # ------------------------------------------------------------------
    # Folder → ZIP
    # ------------------------------------------------------------------

    def _download_folder_as_zip(
        self, folder_id: str, dest_dir: Path, zip_name: str
    ) -> Path:
        """Box フォルダを ZIP にアーカイブしてダウンロードする。"""
        # Step 1: ZIP ダウンロードジョブを作成
        create_url = f"{_BOX_API_BASE}/zip_downloads"
        body = {
            "download_file_name": zip_name.replace(".zip", ""),
            "items": [{"type": "folder", "id": folder_id}],
        }
        logger.info("Creating zip_download for folder id=%s", folder_id)
        resp = requests.post(
            create_url,
            headers={**self._auth_headers(), "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        download_url: str = data.get("download_url", "")
        status_url: str = data.get("status_url", "")

        if not download_url:
            raise RuntimeError(
                f"zip_downloads did not return download_url: {data}"
            )

        logger.info("zip_downloads download_url obtained; starting download")

        # Step 2: download_url は有効期限が短いので即座にダウンロード
        dl_resp = requests.get(download_url, stream=True, timeout=120)
        dl_resp.raise_for_status()

        out_path = dest_dir / zip_name
        _stream_to_file(dl_resp, out_path)

        size = out_path.stat().st_size
        logger.info("Folder ZIP downloaded: %s (%d bytes)", out_path, size)
        return out_path


def _stream_to_file(resp: requests.Response, path: Path) -> None:
    """レスポンスをストリームでファイルに書き出す。"""
    with open(path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
