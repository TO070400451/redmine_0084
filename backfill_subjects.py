"""既存レコードの issue_subject を Redmine から取得して補完する。"""
import sqlite3
from src.config import Config
from src.redmine_client import RedmineClient

cfg = Config()
redmine = RedmineClient(cfg.redmine_base_url, cfg.redmine_api_key)

conn = sqlite3.connect(cfg.db_path)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT journal_id, issue_id FROM journal_events WHERE issue_subject IS NULL"
).fetchall()

print(f"{len(rows)} 件のレコードを補完します...")

done = {}  # issue_id → subject のキャッシュ
for row in rows:
    issue_id = row["issue_id"]
    if issue_id not in done:
        try:
            issue = redmine.get_issue_with_journals(issue_id)
            done[issue_id] = issue.get("subject", "")
            print(f"  #{issue_id}: {done[issue_id]}")
        except Exception as e:
            print(f"  #{issue_id}: 取得失敗 ({e})")
            done[issue_id] = ""

    conn.execute(
        "UPDATE journal_events SET issue_subject=? WHERE journal_id=?",
        (done[issue_id], row["journal_id"]),
    )

conn.commit()
conn.close()
print("完了")
