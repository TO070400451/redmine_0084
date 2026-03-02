from __future__ import annotations

"""
Box OAuth2 トークン管理。
アクセストークンが失効した場合にリフレッシュトークンで自動更新する。
"""

import logging
import re
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.box.com/oauth2/token"


class TokenManager:
    """access_token / refresh_token を管理し、必要に応じて自動更新する。"""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        access_token: str,
        refresh_token: str,
        env_path: str = ".env",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._env_path = Path(env_path)

    @property
    def access_token(self) -> str:
        return self._access_token

    def refresh(self) -> str:
        """リフレッシュトークンを使って新しいアクセストークンを取得し .env を更新する。"""
        logger.info("Box access token expired, refreshing...")
        resp = requests.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        })
        resp.raise_for_status()
        data = resp.json()

        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]

        self._save_env({
            "BOX_ACCESS_TOKEN": self._access_token,
            "BOX_REFRESH_TOKEN": self._refresh_token,
        })
        logger.info("Box token refreshed and saved to .env")
        return self._access_token

    def _save_env(self, updates: dict[str, str]) -> None:
        text = self._env_path.read_text(encoding="utf-8")
        for key, value in updates.items():
            pattern = rf"^{re.escape(key)}=.*$"
            replacement = f"{key}={value}"
            if re.search(pattern, text, flags=re.MULTILINE):
                text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
            else:
                text = text.rstrip("\n") + f"\n{replacement}\n"
        self._env_path.write_text(text, encoding="utf-8")
