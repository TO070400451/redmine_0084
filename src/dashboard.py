from __future__ import annotations

"""Redmine 監視ダッシュボード HTML を生成する。"""

import json
import logging
from datetime import datetime, timezone, timedelta

_JST = timezone(timedelta(hours=9))
from pathlib import Path

from .state_store import StateStore

logger = logging.getLogger(__name__)

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="30">
  <title>Redmine 監視ダッシュボード</title>
  <style>
    body {{ font-family: 'Segoe UI', sans-serif; margin: 24px; background: #f5f5f5; }}
    h1 {{ color: #333; font-size: 1.4em; margin-bottom: 4px; }}
    .updated {{ color: #888; font-size: 0.85em; margin-bottom: 16px; }}
    table {{ border-collapse: collapse; width: 100%; background: #fff; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }}
    th {{ background: #4a6fa5; color: #fff; padding: 10px 14px; text-align: left; font-size: 0.9em; }}
    td {{ padding: 10px 14px; border-bottom: 1px solid #eee; font-size: 0.9em; vertical-align: top; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #f0f4ff; }}
    a {{ color: #4a6fa5; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .excerpt {{ color: #555; max-width: 400px; white-space: pre-wrap; word-break: break-all; }}
    .empty {{ color: #999; text-align: center; padding: 32px; }}
    .dl-btn {{ padding: 4px 12px; background: #4a6fa5; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 0.85em; }}
    .dl-btn:hover {{ background: #3a5f95; }}
    .dl-btn:disabled {{ background: #aaa; cursor: default; }}
    .del-btn {{ padding: 4px 8px; background: #e0e0e0; color: #666; border: none; border-radius: 4px; cursor: pointer; font-size: 0.8em; }}
    .del-btn:hover {{ background: #c00; color: #fff; }}
    .status {{ font-size: 0.8em; color: #888; margin-top: 4px; }}
    .val-ok {{ color: #2a7a2a; font-size: 0.85em; }}
    .val-ng {{ color: #c00; font-size: 0.85em; }}
    .val-defects {{ margin-top: 4px; font-size: 0.78em; color: #c00; white-space: pre-wrap; word-break: break-all; max-width: 320px; }}
    .val-spin {{ color: #888; font-size: 0.85em; }}
  </style>
</head>
<body>
  <h1>Redmine 監視ダッシュボード</h1>
  <div class="updated">最終更新: {updated_at}（30秒ごとに自動更新）</div>
  {content}
</body>
</html>
"""

_ROW_TEMPLATE = """\
    <tr>
      <td><a href="{ticket_url}" target="_blank">#{issue_id}</a></td>
      <td>{issue_subject}</td>
      <td>{detected_at}</td>
      <td class="excerpt">{comment_excerpt}</td>
      <td>{dl_cell}</td>
      <td><button class="del-btn" onclick="dismissRecord({journal_id}, this)">削除</button></td>
    </tr>
"""

_DL_BTN = '<button class="dl-btn" onclick="triggerDownload({journal_id}, this)">DL</button><div class="status" id="st-{journal_id}">{status_label}</div>'
_DL_DONE = '<span style="color:#888;font-size:0.85em;">{status_label}</span>'


_STATUS_LABELS = {
    "notified": "",
    "detected": "",
    "decided": "処理待ち",
    "validating": "検証中...",
    "downloading": "DL中...",
    "extracted": "完了",
    "failed": "失敗",
    "skip": "スキップ",
}

_DL_SCRIPT = """
<script>
async function triggerDownload(journalId, btn) {
  btn.disabled = true;
  const st = document.getElementById('st-' + journalId);
  if (st) st.textContent = '開始中...';
  try {
    const resp = await fetch('/download/' + journalId, {method: 'POST'});
    const data = await resp.json();
    if (resp.ok) {
      if (st) st.textContent = '検証中...';
      pollStatus(journalId, st, btn);
    } else {
      if (st) st.textContent = 'エラー';
      btn.disabled = false;
    }
  } catch(e) {
    if (st) st.textContent = 'エラー';
    btn.disabled = false;
  }
}
async function dismissRecord(journalId, btn) {
  if (!window.confirm('このレコードをダッシュボードから削除しますか？')) return;
  btn.disabled = true;
  try {
    const resp = await fetch('/dismiss/' + journalId, {method: 'POST'});
    if (resp.ok) {
      const row = btn.closest('tr');
      if (row) row.remove();
    } else {
      btn.disabled = false;
      alert('削除に失敗しました');
    }
  } catch(e) {
    btn.disabled = false;
    alert('削除に失敗しました');
  }
}
function pollStatus(journalId, st, btn) {
  const iv = setInterval(async () => {
    try {
      const resp = await fetch('/status/' + journalId);
      const data = await resp.json();
      const s = data.status;
      const vs = data.validation_status;
      if (s === 'extracted') {
        clearInterval(iv);
        if (st) st.textContent = '完了';
        btn.textContent = '✓ 完了';
        btn.disabled = true;
      } else if (s === 'failed') {
        clearInterval(iv);
        // ページリロードで瑕疵詳細をサーバー描画で表示
        window.location.reload();
      } else if (s === 'validating') {
        if (st) st.textContent = '検証中...';
      } else if (s === 'downloading') {
        if (st) st.textContent = 'DL中...';
      } else {
        if (st) st.textContent = s;
      }
    } catch(e) { clearInterval(iv); }
  }, 3000);
}
</script>
"""


def generate(store: StateStore, output_path: str) -> None:
    """ダッシュボード HTML を生成して output_path に保存する。"""
    records = store.get_dashboard_records()
    updated_at = datetime.now(_JST).strftime("%Y-%m-%d %H:%M:%S JST")

    if not records:
        content = '<p class="empty">検出されたチケットはありません。</p>'
    else:
        rows = []
        for r in records:
            _dt_raw = r["detected_at"] or ""
            try:
                _dt = datetime.fromisoformat(_dt_raw).astimezone(_JST)
                detected_at = _dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                detected_at = _dt_raw[:19].replace("T", " ")
            issue_subject = _esc(r["issue_subject"] or "(タイトル不明)")
            comment_excerpt = _esc(r["comment_excerpt"] or "")
            ticket_url = r["ticket_url"] or ""
            issue_id = r["issue_id"]
            journal_id = r["journal_id"]
            status = r["status"] or ""
            has_box = bool(r["box_links_json"] and r["box_links_json"] != "[]")

            status_label = _STATUS_LABELS.get(status, status)
            validation_status = r["validation_status"] if "validation_status" in r.keys() else None
            validation_defects_json = r["validation_defects_json"] if "validation_defects_json" in r.keys() else None

            if not has_box:
                dl_cell = '<span style="color:#ccc;font-size:0.85em;">—</span>'
            elif status in ("notified", "detected"):
                dl_cell = _DL_BTN.format(journal_id=journal_id, status_label="")
            elif status == "validating":
                dl_cell = '<span class="val-spin">検証中...</span>'
            elif validation_status == "validation_ng":
                defects = json.loads(validation_defects_json or "[]")
                defect_lines = "\n".join(f"・{_esc(d.split(chr(10))[0])}" for d in defects)
                dl_cell = (
                    '<span class="val-ng">❌ 瑕疵あり</span>'
                    + (f'<div class="val-defects">{defect_lines}</div>' if defect_lines else "")
                )
            elif validation_status == "validation_ok" and status == "extracted":
                dl_cell = '<span class="val-ok">✓ 完了</span>'
            elif validation_status == "validation_ok" and status == "downloading":
                dl_cell = (
                    f'<button class="dl-btn" onclick="triggerDownload({journal_id}, this)">再試行</button>'
                    f'<div class="status" id="st-{journal_id}">DL中断</div>'
                )
            elif status == "downloading":
                dl_cell = (
                    f'<button class="dl-btn" onclick="triggerDownload({journal_id}, this)">再試行</button>'
                    f'<div class="status" id="st-{journal_id}">DL中断</div>'
                )
            elif status == "failed":
                last_error = _esc((r["last_error"] or "")[:80])
                dl_cell = (
                    f'<button class="dl-btn" onclick="triggerDownload({journal_id}, this)">再試行</button>'
                    f'<div class="status" id="st-{journal_id}">失敗: {last_error}</div>'
                )
            else:
                dl_cell = _DL_DONE.format(status_label=status_label)

            rows.append(_ROW_TEMPLATE.format(
                ticket_url=ticket_url,
                issue_id=issue_id,
                issue_subject=issue_subject,
                detected_at=detected_at,
                comment_excerpt=comment_excerpt,
                journal_id=journal_id,
                dl_cell=dl_cell,
            ))
        content = (
            "<table>"
            "<tr><th>#</th><th>タイトル</th><th>検出日時</th><th>コメント（抜粋）</th><th>Box</th><th></th></tr>"
            + "".join(rows)
            + "</table>"
            + _DL_SCRIPT
        )

    html = _HTML_TEMPLATE.format(updated_at=updated_at, content=content)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    logger.info("Dashboard updated: %s (%d records)", output_path, len(records))


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
