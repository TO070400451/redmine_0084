from __future__ import annotations

"""
ZIP 解凍と meta.json 生成。
"""

import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def extract_zip(
    zip_path: Path,
    extract_dir: Path,
    allow_overwrite: bool = True,
) -> list[Path]:
    """
    ZIP を解凍し、抽出したファイルのパスリストを返す。

    Raises:
        zipfile.BadZipFile: ZIP が破損している場合
        ValueError: パストラバーサルが検出された場合
    """
    extract_dir.mkdir(parents=True, exist_ok=True)

    extracted: list[Path] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            # パストラバーサル対策
            out_path = (extract_dir / member.filename).resolve()
            if not str(out_path).startswith(str(extract_dir.resolve())):
                raise ValueError(
                    f"Path traversal detected in ZIP member: {member.filename}"
                )
            zf.extract(member, extract_dir)
            extracted.append(extract_dir / member.filename)

    logger.info(
        "Extracted %d files from %s to %s",
        len(extracted),
        zip_path,
        extract_dir,
    )
    return extracted


def write_meta(
    work_dir: Path,
    issue_id: int,
    journal_id: int,
    ticket_url: str,
    matched_pattern: Optional[str],
    score: Optional[int],
    evidence: list[str],
    box_links: list[str],
    box_item_type: Optional[str],
    box_item_id: Optional[str],
    download_status: str,
    extract_status: str,
    error_summary: Optional[str] = None,
) -> Path:
    """meta.json を work_dir に書き出す。"""
    meta: dict[str, Any] = {
        "issue_id": issue_id,
        "journal_id": journal_id,
        "ticket_url": ticket_url,
        "pattern": matched_pattern,
        "score": score,
        "evidence": evidence,
        "box_links": box_links,
        "box_item_type": box_item_type,
        "box_item_id": box_item_id,
        "download_status": download_status,
        "extract_status": extract_status,
        "error_summary": error_summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = work_dir / "meta.json"
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("meta.json written: %s", meta_path)
    return meta_path
