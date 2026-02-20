"""PatternMatcher のユニットテスト。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from src.pattern_matcher import PatternMatcher, MatchResult

SAMPLE_PATTERNS = {
    "patterns": [
        {
            "pattern_id": "test_pattern",
            "name": "テストパターン",
            "keywords": {
                "must": ["ログ"],
                "should": ["解析", "手順"],
                "must_not": ["完了"],
            },
            "regex_rules": [
                {"regex": "(exception|crash)", "weight": 15}
            ],
            "link_rules": {"box_link_bonus": 10},
            "threshold": {"notify_min_score": 20},
        }
    ]
}


@pytest.fixture
def patterns_yaml(tmp_path: Path) -> str:
    p = tmp_path / "patterns.yaml"
    p.write_text(yaml.dump(SAMPLE_PATTERNS, allow_unicode=True), encoding="utf-8")
    return str(p)


@pytest.fixture
def matcher(patterns_yaml: str) -> PatternMatcher:
    return PatternMatcher(patterns_yaml)


class TestPatternMatcher:
    def test_must_keyword_hit(self, matcher: PatternMatcher) -> None:
        results = matcher.match(["ログを添付します"])
        assert len(results) == 1
        assert results[0].score >= 20
        assert any("[must] ログ" in e for e in results[0].evidence)

    def test_must_not_reduces_score(self, matcher: PatternMatcher) -> None:
        # must hit (+20) + must_not hit (-30) = -10 → clipped to 0 → below threshold
        results = matcher.match(["ログ解析が完了しました"])
        # score = 20 (must) + 8 (should:解析) - 30 (must_not) = -2 → 0 < threshold(20)
        assert len(results) == 0

    def test_regex_hit(self, matcher: PatternMatcher) -> None:
        results = matcher.match(["ログ", "crashが発生しました"])
        assert len(results) == 1
        assert any("[regex]" in e for e in results[0].evidence)

    def test_box_link_bonus(self, matcher: PatternMatcher) -> None:
        results_no_box = matcher.match(["ログ"], has_box_link=False)
        results_with_box = matcher.match(["ログ"], has_box_link=True)
        assert results_with_box[0].score > results_no_box[0].score

    def test_no_match_below_threshold(self, matcher: PatternMatcher) -> None:
        results = matcher.match(["関係ないテキスト"])
        assert len(results) == 0

    def test_score_capped_at_100(self, matcher: PatternMatcher) -> None:
        # 大量のキーワードでも 100 を超えない
        text = "ログ 解析 手順 exception crash"
        results = matcher.match([text], has_box_link=True)
        assert len(results) > 0
        assert results[0].score <= 100

    def test_results_sorted_by_score(self, patterns_yaml: str, tmp_path: Path) -> None:
        # 2つのパターンを持つ YAML で降順を確認
        two_patterns = {
            "patterns": [
                {
                    "pattern_id": "low",
                    "name": "低スコア",
                    "keywords": {"must": ["A"], "should": [], "must_not": []},
                    "regex_rules": [],
                    "link_rules": {},
                    "threshold": {"notify_min_score": 10},
                },
                {
                    "pattern_id": "high",
                    "name": "高スコア",
                    "keywords": {"must": ["A", "B"], "should": ["C"], "must_not": []},
                    "regex_rules": [],
                    "link_rules": {},
                    "threshold": {"notify_min_score": 10},
                },
            ]
        }
        p = tmp_path / "two.yaml"
        p.write_text(yaml.dump(two_patterns, allow_unicode=True), encoding="utf-8")
        m = PatternMatcher(str(p))
        results = m.match(["A B C"])
        assert len(results) == 2
        assert results[0].score >= results[1].score
