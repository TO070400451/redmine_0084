from __future__ import annotations

"""
Teams Bot Framework Adaptive Card 応答を受け取る FastAPI サーバー。

Bot Framework から POST で届いたアクティビティを解釈し、
Action.Submit の payload を読んで StateStore に decision を記録する。
"""

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response

logger = logging.getLogger(__name__)

app = FastAPI(title="Redmine-Teams-Box Bot Server")

# StateStore はランタイムに差し込む（main.py で設定）
_state_store: Any = None


def set_state_store(store: Any) -> None:
    global _state_store
    _state_store = store


@app.post("/api/messages")
async def messages(request: Request) -> Response:
    """Bot Framework からのアクティビティを受信するエンドポイント。"""
    try:
        body: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    activity_type: str = body.get("type", "")
    logger.debug("Received activity type=%s", activity_type)

    if activity_type == "invoke" or activity_type == "message":
        _handle_adaptive_card_submit(body)
    elif activity_type == "conversationUpdate":
        logger.info("conversationUpdate received (bot added to chat)")
    else:
        logger.debug("Unhandled activity type: %s", activity_type)

    # Bot Framework は 200 OK を期待する
    return Response(status_code=200)


def _handle_adaptive_card_submit(body: dict[str, Any]) -> None:
    """Action.Submit payload から decision を取り出して状態を更新する。"""
    if _state_store is None:
        logger.error("StateStore not configured in bot_server")
        return

    # Bot Framework の Action.Submit は value フィールドに payload が入る
    value: dict[str, Any] = body.get("value", {})
    if not value:
        # テキストメッセージ等は無視
        return

    payload_type = value.get("type", "")
    if payload_type != "decision":
        logger.debug("Non-decision payload received: type=%s", payload_type)
        return

    journal_id = value.get("journal_id")
    decision = value.get("decision")  # "work" | "skip"

    if journal_id is None or decision not in ("work", "skip"):
        logger.warning("Invalid decision payload: %s", value)
        return

    logger.info(
        "Decision received from Teams: journal_id=%s decision=%s",
        journal_id,
        decision,
    )
    _state_store.set_decision(int(journal_id), decision)
