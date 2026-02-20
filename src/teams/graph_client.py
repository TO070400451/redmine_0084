from __future__ import annotations

import json
import logging
from typing import Any

import requests

from ..utils import mask_secret

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_TOKEN_URL_TEMPLATE = (
    "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
)


class GraphClient:
    """Microsoft Graph API クライアント（Teams メッセージ送信）。"""

    def __init__(
        self, tenant_id: str, client_id: str, client_secret: str
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None

    def _get_token(self) -> str:
        url = _TOKEN_URL_TEMPLATE.format(tenant_id=self._tenant_id)
        resp = requests.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=30,
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
        logger.debug("Graph token acquired (len=%d)", len(token))
        return token

    def _headers(self) -> dict[str, str]:
        if not self._token:
            self._token = self._get_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def send_adaptive_card_to_chat(
        self, chat_id: str, card: dict[str, Any]
    ) -> dict[str, Any]:
        """Graph API でチャットに Adaptive Card を送信する。"""
        url = f"{_GRAPH_BASE}/chats/{chat_id}/messages"
        body = {
            "body": {
                "contentType": "html",
                "content": "<attachment id='card1'></attachment>",
            },
            "attachments": [
                {
                    "id": "card1",
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": json.dumps(card),
                }
            ],
        }
        resp = requests.post(url, headers=self._headers(), json=body, timeout=30)
        if resp.status_code == 401:
            # トークン失効時に再取得してリトライ
            self._token = self._get_token()
            resp = requests.post(
                url, headers=self._headers(), json=body, timeout=30
            )
        resp.raise_for_status()
        return resp.json()

    def send_adaptive_card_to_channel(
        self, team_id: str, channel_id: str, card: dict[str, Any]
    ) -> dict[str, Any]:
        """Graph API でチャンネルに Adaptive Card を送信する。"""
        url = f"{_GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages"
        body = {
            "body": {
                "contentType": "html",
                "content": "<attachment id='card1'></attachment>",
            },
            "attachments": [
                {
                    "id": "card1",
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": json.dumps(card),
                }
            ],
        }
        resp = requests.post(url, headers=self._headers(), json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()
