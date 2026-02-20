from __future__ import annotations

"""
Box 共有リンクが指す実体（file / folder）を特定する。

Box API: GET https://api.box.com/2.0/shared_items
"""

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_SHARED_ITEMS_URL = "https://api.box.com/2.0/shared_items"


class SharedItemResolver:
    """Box 共有リンクから item_type と item_id を解決する。"""

    def __init__(self, access_token: str, shared_link_password: str = "") -> None:
        self._token = access_token
        self._password = shared_link_password

    def resolve(self, shared_link: str) -> dict[str, Any]:
        """
        Returns:
            {"type": "file"|"folder", "id": "<item_id>", "name": "..."}

        Raises:
            requests.HTTPError: API エラー
            ValueError: 予期しないレスポンス
        """
        box_api_header = f"shared_link={shared_link}"
        if self._password:
            box_api_header += f"&shared_link_password={self._password}"

        headers = {
            "Authorization": f"Bearer {self._token}",
            "BoxApi": box_api_header,
        }
        resp = requests.get(_SHARED_ITEMS_URL, headers=headers, timeout=30)

        if resp.status_code == 404:
            raise ValueError(
                f"Box shared link not found or access denied: {shared_link}"
            )
        resp.raise_for_status()

        data = resp.json()
        item_type = data.get("type")
        item_id = data.get("id")
        item_name = data.get("name", "")

        if item_type not in ("file", "folder"):
            raise ValueError(
                f"Unexpected Box item type: {item_type} for link: {shared_link}"
            )

        logger.info(
            "Resolved Box link: type=%s id=%s name=%s", item_type, item_id, item_name
        )
        return {"type": item_type, "id": item_id, "name": item_name}
