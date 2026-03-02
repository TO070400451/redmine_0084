from __future__ import annotations

"""test_result.html の Fingerprint と Failed Tests を解析する。"""

import re
from dataclasses import dataclass, field

_FP_RE = re.compile(
    r'<td[^>]*class="rowtitle"[^>]*>Fingerprint</td>\s*<td[^>]*>(.*?)</td>',
    re.DOTALL | re.IGNORECASE,
)
_FAILED_SECTION_RE = re.compile(
    r'<h2[^>]*>Failed\s+Tests.*?</h2>(.*?)(?=<h2|$)',
    re.DOTALL | re.IGNORECASE,
)
_MODULE_RE = re.compile(
    r'<td[^>]*class="module"[^>]*>.*?>(.*?)</(?:a|td)>',
    re.DOTALL | re.IGNORECASE,
)
_TESTNAME_RE = re.compile(
    r'<td[^>]*class="testname"[^>]*>(.*?)</td>',
    re.DOTALL | re.IGNORECASE,
)
_ABI_RE = re.compile(r'^(arm64-v8a|armeabi-v7a|x86_64|x86)\s+')


@dataclass
class HtmlResult:
    fingerprint: str = ""
    # {module_name: [test_name, ...]}
    failed_tests: dict[str, list[str]] = field(default_factory=dict)


def parse(html: str) -> HtmlResult:
    result = HtmlResult()

    # Fingerprint
    m = _FP_RE.search(html)
    if m:
        result.fingerprint = m.group(1).strip()

    # Failed Tests セクション
    sec_m = _FAILED_SECTION_RE.search(html)
    if not sec_m:
        return result
    section = sec_m.group(1)

    # モジュール行とテスト行を位置順に処理
    events: list[tuple[int, str, str]] = []
    for m in _MODULE_RE.finditer(section):
        raw = re.sub(r"&nbsp;|&#[xX]?[0-9a-fA-F]+;", " ", m.group(1)).strip()
        module_name = _ABI_RE.sub("", raw).strip()
        events.append((m.start(), "module", module_name))
    for m in _TESTNAME_RE.finditer(section):
        events.append((m.start(), "test", m.group(1).strip()))
    events.sort()

    current = ""
    for _, etype, value in events:
        if etype == "module":
            current = value
            result.failed_tests.setdefault(current, [])
        elif etype == "test" and current:
            result.failed_tests[current].append(value)

    return result


def fingerprint_parts(fp: str) -> dict[str, str]:
    """Fingerprint を '/' で分割して機種コードとソフトバージョンを返す。"""
    parts = fp.split("/")
    return {
        "device_code": parts[1] if len(parts) > 1 else "",
        "sw_version": parts[4].split(":")[0] if len(parts) > 4 else "",
    }
