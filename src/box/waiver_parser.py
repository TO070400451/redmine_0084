from __future__ import annotations

"""
Redmine コメントから Waiver として記載されたテスト名を抽出する。

対応フォーマット:
  〇〇 Waiver としています。
  ・ModuleName
  →android.foo.bar.ClassName#methodName
  →android.foo.bar.ClassName#otherMethod
  https://...（任意のURL行は無視）
"""

import re

# Waiver セクション開始を示すキーワード
_WAIVER_RE = re.compile(r'waiver', re.IGNORECASE)

# テスト名行: → で始まる（→ や > を許容）
_TEST_ARROW_RE = re.compile(r'^[→>]\s*(.+)$')

# Waiver セクション終了マーカー（別セクションの開始）
_SECTION_END_RE = re.compile(r'不具合チケット|下記試験.*起票')


def extract_waiver_tests(text: str) -> set[str]:
    """Redmine コメントテキストから Waiver として記載されたテスト名を返す。"""
    waiver: set[str] = set()
    in_waiver = False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _WAIVER_RE.search(stripped):
            in_waiver = True
            continue
        if _SECTION_END_RE.search(stripped):
            in_waiver = False
            continue
        if in_waiver:
            m = _TEST_ARROW_RE.match(stripped)
            if m:
                waiver.add(m.group(1).strip())

    return waiver
