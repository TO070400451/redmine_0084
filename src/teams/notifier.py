from __future__ import annotations

import json
import logging
from typing import Any

import requests

from ..utils import mask_secret
from .adaptive_card import build_card
from .graph_client import GraphClient

logger = logging.getLogger(__name__)

_BOT_TOKEN_URL = (
    "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
)
_BOT_SERVICE_URL = "https://smba.trafficmanager.net/teams/"


class TeamsNotifier:
    """Teams への通知送信（Bot / Graph 両方式対応）。"""

    def __init__(self, cfg: Any) -> None:
        self._cfg = cfg
        self._graph: GraphClient | None = None
        if cfg.teams_mode == "graph":
            self._graph = GraphClient(
                tenant_id=cfg.ms_tenant_id,
                client_id=cfg.ms_client_id,
                client_secret=cfg.ms_client_secret,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(
        self,
        journal_id: int,
        issue_id: int,
        ticket_url: str,
        pattern_name: str,
        score: int,
        evidence: list[str],
        box_links: list[str],
    ) -> None:
        card = build_card(
            journal_id=journal_id,
            issue_id=issue_id,
            ticket_url=ticket_url,
            pattern_name=pattern_name,
            score=score,
            evidence=evidence,
            box_links=box_links,
        )

        if self._cfg.teams_mode == "graph":
            self._send_graph(card)
        else:
            self._send_bot(card)

        logger.info(
            "Teams notification sent: journal_id=%d pattern=%s score=%d",
            journal_id,
            pattern_name,
            score,
        )

    # ------------------------------------------------------------------
    # Bot mode
    # ------------------------------------------------------------------

    def _get_bot_token(self) -> str:
        resp = requests.post(
            _BOT_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self._cfg.bot_app_id,
                "client_secret": self._cfg.bot_app_password,
                "scope": "https://api.botframework.com/.default",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _send_bot(self, card: dict[str, Any]) -> None:
        """Bot Framework Connector API でメッセージを送信する。"""
        token = self._get_bot_token()
        conversation_id = self._cfg.teams_chat_id
        url = (
            f"{_BOT_SERVICE_URL}v3/conversations/{conversation_id}/activities"
        )
        activity = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": card,
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, headers=headers, json=activity, timeout=30)
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Graph mode
    # ------------------------------------------------------------------

    def _send_graph(self, card: dict[str, Any]) -> None:
        assert self._graph is not None
        chat_id = self._cfg.teams_chat_id
        self._graph.send_adaptive_card_to_chat(chat_id, card)
