from __future__ import annotations

"""ダッシュボード表示 + Box ダウンロードトリガー用 Web サーバー。"""

import logging
import threading
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from . import dashboard
from .config import Config
from .state_store import StateStore

logger = logging.getLogger(__name__)

app = FastAPI()

_store: Optional[StateStore] = None
_cfg: Optional[Config] = None
_download_callback = None  # journal_id を受け取る関数


def init(cfg: Config, store: StateStore, download_callback) -> None:
    global _store, _cfg, _download_callback
    _cfg = cfg
    _store = store
    _download_callback = download_callback


@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    if _cfg is None or _store is None:
        raise HTTPException(status_code=503, detail="Not initialized")
    dashboard.generate(_store, _cfg.dashboard_path)
    from pathlib import Path
    html = Path(_cfg.dashboard_path).read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.post("/download/{journal_id}")
def trigger_download(journal_id: int):
    if _store is None or _download_callback is None:
        raise HTTPException(status_code=503, detail="Not initialized")

    row = _store.get(journal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Journal not found")
    if not row["box_links_json"] or row["box_links_json"] == "[]":
        raise HTTPException(status_code=400, detail="No Box links")

    # すでに処理中・完了のものは多重実行しない
    current_status = row["status"] or ""
    if current_status in ("validating", "downloading", "extracted"):
        return {"status": current_status, "journal_id": journal_id}

    # decision を work にセット（状態管理）
    _store.set_decision(journal_id, "work")
    # 最新行を取得して渡す
    row = _store.get(journal_id)

    # バックグラウンドで実行
    thread = threading.Thread(
        target=_download_callback,
        args=(row,),
        daemon=True,
        name=f"box-dl-{journal_id}",
    )
    thread.start()
    logger.info("Box download triggered: journal_id=%d", journal_id)
    return {"status": "started", "journal_id": journal_id}


@app.get("/status/{journal_id}")
def get_status(journal_id: int):
    if _store is None:
        raise HTTPException(status_code=503, detail="Not initialized")
    row = _store.get(journal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    keys = row.keys()
    return {
        "journal_id": journal_id,
        "status": row["status"],
        "validation_status": row["validation_status"] if "validation_status" in keys else None,
        "last_error": (row["last_error"] or "")[:120] if "last_error" in keys else None,
    }


def start(cfg: Config) -> None:
    """Web サーバーを別スレッドで起動する。"""
    def _run():
        uvicorn.run(app, host="127.0.0.1", port=cfg.web_port, log_level="warning")

    thread = threading.Thread(target=_run, daemon=True, name="web-server")
    thread.start()
    logger.info("Web server started: http://127.0.0.1:%d", cfg.web_port)
