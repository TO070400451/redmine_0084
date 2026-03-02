from __future__ import annotations

"""
Box フォルダのバリデーション。

チェック内容:
  ① Fingerprint の機種コード（/区切り2番目）が全 HTML で一致
  ② Fingerprint のソフトバージョン（/区切り5番目）が全 HTML で一致
  ③ 大きな試験項目内で FAIL が再試行で解消されているか
"""

import logging
from dataclasses import dataclass, field
from collections import defaultdict

from . import html_parser
from .folder_walker import find_files, download_text, get_folder_name, resolve_folder_id

logger = logging.getLogger(__name__)

EXCLUDE_FOLDERS = {"00_承認通知", "02_CTS Verifier"}
ROOT_FOLDER_NAME = "00_提出"


@dataclass
class ValidationResult:
    ok: bool
    defects: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate(box_url: str, token: str) -> ValidationResult:
    """Box URL（直接リンクまたは共有リンク）を検証する。"""
    try:
        folder_id = resolve_folder_id(box_url, token)
    except Exception as e:
        return ValidationResult(ok=False, defects=[f"Box URL の解決に失敗: {e}"])
    return _validate_folder(folder_id, token)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _validate_folder(folder_id: str, token: str) -> ValidationResult:
    defects: list[str] = []

    # 1. トップフォルダ名チェック
    try:
        name = get_folder_name(folder_id, token)
    except Exception as e:
        return ValidationResult(ok=False, defects=[f"フォルダ情報の取得に失敗: {e}"])

    if name != ROOT_FOLDER_NAME:
        return ValidationResult(
            ok=False,
            defects=[
                f"最上段フォルダ名が「{ROOT_FOLDER_NAME}」ではありません（実際:「{name}」）。"
                " 正しい Box URL を確認してください。"
            ],
        )

    # 2. test_result.html を収集
    try:
        html_files = find_files(folder_id, token, exclude_top=EXCLUDE_FOLDERS)
    except Exception as e:
        return ValidationResult(ok=False, defects=[f"HTML ファイル検索に失敗: {e}"])

    if not html_files:
        return ValidationResult(ok=False, defects=["test_result.html が見つかりませんでした"])

    logger.info("Validation: found %d test_result.html files", len(html_files))

    # 3. 各 HTML を解析
    parsed: list[dict] = []
    for hf in html_files:
        try:
            html = download_text(hf.file_id, token)
            result = html_parser.parse(html)
            parsed.append({
                "path": hf.path,
                "fingerprint": result.fingerprint,
                "failed_tests": result.failed_tests,
            })
        except Exception as e:
            logger.warning("HTML 解析スキップ %s: %s", hf.path, e)

    # 4. チェック ①② Fingerprint の一貫性
    defects.extend(_check_fingerprint(parsed))

    # 5. チェック ③ FAIL の解消確認（カテゴリ内で判断）
    defects.extend(_check_fail_resolution(parsed))

    return ValidationResult(ok=len(defects) == 0, defects=defects)


def _check_fingerprint(parsed: list[dict]) -> list[str]:
    defects = []
    device_codes: dict[str, str] = {}
    sw_versions: dict[str, str] = {}

    for r in parsed:
        fp = r["fingerprint"]
        if not fp:
            continue
        parts = html_parser.fingerprint_parts(fp)
        if parts["device_code"]:
            device_codes[r["path"]] = parts["device_code"]
        if parts["sw_version"]:
            sw_versions[r["path"]] = parts["sw_version"]

    unique_dc = set(device_codes.values())
    if len(unique_dc) > 1:
        details = _summarize_by_category(device_codes)
        defects.append(f"① 機種コード不一致: {', '.join(sorted(unique_dc))}\n   {details}")

    unique_sw = set(sw_versions.values())
    if len(unique_sw) > 1:
        details = _summarize_by_category(sw_versions)
        defects.append(f"② ソフトバージョン不一致: {', '.join(sorted(unique_sw))}\n   {details}")

    return defects


def _check_fail_resolution(parsed: list[dict]) -> list[str]:
    """
    カテゴリ（トップレベルフォルダ）ごとに FAIL の解消を確認する。

    パス構造:
      メイン実行: <category>/<timestamp>/results/.../test_result.html
      再試行:    <category>/Modules/<ModuleName>/results/.../test_result.html
    """
    defects = []

    # カテゴリごとにグループ化
    by_category: dict[str, list[dict]] = defaultdict(list)
    for r in parsed:
        category = r["path"].split("/")[0]
        parts = r["path"].split("/")
        is_rerun = len(parts) > 1 and parts[1] == "Modules"
        rerun_module = parts[2] if is_rerun and len(parts) > 2 else None
        by_category[category].append({
            **r,
            "is_rerun": is_rerun,
            "rerun_module": rerun_module,
        })

    for category, items in by_category.items():
        # 再試行の失敗テストをモジュールごとに収集
        rerun_failures: dict[str, set[str]] = defaultdict(set)
        rerun_modules: set[str] = set()
        for item in items:
            if not item["is_rerun"] or not item["rerun_module"]:
                continue
            mod = item["rerun_module"]
            rerun_modules.add(mod)
            for tests in item["failed_tests"].values():
                rerun_failures[mod].update(tests)

        # メイン実行の失敗を確認
        for item in items:
            if item["is_rerun"]:
                continue
            for module_label, tests in item["failed_tests"].items():
                if not tests:
                    continue
                if module_label in rerun_modules:
                    # 再試行あり → 再試行後も失敗しているテストが瑕疵
                    still_fail = [t for t in tests if t in rerun_failures[module_label]]
                    if still_fail:
                        defects.append(
                            f"③ [{category}] {module_label}: "
                            f"再試行後も {len(still_fail)} 件失敗\n"
                            + "\n".join(f"   - {t}" for t in still_fail[:5])
                            + (f"\n   ... 他 {len(still_fail)-5} 件" if len(still_fail) > 5 else "")
                        )
                else:
                    # 再試行なし → 全失敗が瑕疵
                    defects.append(
                        f"③ [{category}] {module_label}: "
                        f"再試行なし・{len(tests)} 件失敗\n"
                        + "\n".join(f"   - {t}" for t in tests[:5])
                        + (f"\n   ... 他 {len(tests)-5} 件" if len(tests) > 5 else "")
                    )

    return defects


def _summarize_by_category(path_to_value: dict[str, str]) -> str:
    """パス → 値 の辞書をカテゴリごとに集約して文字列にする。"""
    by_cat: dict[str, set[str]] = defaultdict(set)
    for path, val in path_to_value.items():
        cat = path.split("/")[0]
        by_cat[cat].add(val)
    return " / ".join(f"{cat}:{','.join(sorted(vs))}" for cat, vs in sorted(by_cat.items()))
