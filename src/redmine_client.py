from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


class RedmineClient:
    """Redmine REST API クライアント。"""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.verify = False
        self._session.headers.update(
            {
                "X-Redmine-API-Key": api_key,
                "Accept": "application/json",
            }
        )

    def _get(
        self, path: str, params: dict | None = None, retries: int = 3
    ) -> Any:
        url = f"{self.base_url}{path}"
        delay = 2.0
        for attempt in range(1, retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                logger.warning(
                    "Redmine API error (attempt %d/%d) %s: %s",
                    attempt,
                    retries,
                    url,
                    exc,
                )
                if attempt == retries:
                    raise
                time.sleep(delay)
                delay *= 2

    def get_updated_issues(
        self, project_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """最新更新順で issue 一覧を取得する。"""
        data = self._get(
            "/issues.json",
            params={
                "project_id": project_id,
                "sort": "updated_on:desc",
                "limit": limit,
                "status_id": "*",
            },
        )
        return data.get("issues", [])

    def get_issue_with_journals(self, issue_id: int) -> dict[str, Any]:
        """journals を含む issue 詳細を取得する。"""
        data = self._get(
            f"/issues/{issue_id}.json", params={"include": "journals"}
        )
        return data.get("issue", {})
