from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    pattern_id: str
    name: str
    score: int
    evidence: list[str] = field(default_factory=list)
    notify_min_score: int = 50


class PatternMatcher:
    """patterns.yaml のルールで journal テキストをスコアリングする。"""

    def __init__(self, patterns_yaml: str) -> None:
        with open(patterns_yaml, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.patterns: list[dict[str, Any]] = data.get("patterns", [])
        logger.info("Loaded %d patterns from %s", len(self.patterns), patterns_yaml)

    def match(
        self, texts: list[str], has_box_link: bool = False
    ) -> list[MatchResult]:
        """全パターンをスコアリングし、notify_min_score 以上を返す（降順）。"""
        combined = "\n".join(t for t in texts if t)
        results: list[MatchResult] = []

        for pat in self.patterns:
            score = 0
            evidence: list[str] = []
            keywords: dict[str, list[str]] = pat.get("keywords", {})
            threshold_cfg: dict[str, Any] = pat.get("threshold", {})
            notify_min = int(threshold_cfg.get("notify_min_score", 50))

            for kw in keywords.get("must", []):
                if kw in combined:
                    score += 20
                    evidence.append(f"[must] {kw}")

            for kw in keywords.get("should", []):
                if kw in combined:
                    score += 20
                    evidence.append(f"[should] {kw}")

            for kw in keywords.get("must_not", []):
                if kw in combined:
                    score -= 30
                    evidence.append(f"[must_not] {kw}")

            for rule in pat.get("regex_rules", []):
                rx: str = rule.get("regex", "")
                w: int = int(rule.get("weight", 15))
                if rx and re.search(rx, combined, re.IGNORECASE):
                    score += w
                    evidence.append(f"[regex] {rx}")

            if has_box_link:
                bonus: int = int(
                    pat.get("link_rules", {}).get("box_link_bonus", 0)
                )
                if bonus:
                    score += bonus
                    evidence.append(f"[box_link] +{bonus}")

            for kw in pat.get("veto_keywords", []):
                if kw in combined:
                    score = 0
                    evidence.append(f"[veto] {kw}")
                    break

            score = max(0, min(100, score))

            if score >= notify_min:
                results.append(
                    MatchResult(
                        pattern_id=pat["pattern_id"],
                        name=pat["name"],
                        score=score,
                        evidence=evidence,
                        notify_min_score=notify_min,
                    )
                )

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def requires_box_validation(self, pattern_id: str) -> bool:
        """パターンに validate_box: false が設定されていなければ True を返す。"""
        for pat in self.patterns:
            if pat.get("pattern_id") == pattern_id:
                return pat.get("validate_box", True)
        return True

    def get_download_mode(self, pattern_id: str) -> str:
        """パターンの download_mode を返す（未設定なら 'zip'）。"""
        for pat in self.patterns:
            if pat.get("pattern_id") == pattern_id:
                return pat.get("download_mode", "zip")
        return "zip"
