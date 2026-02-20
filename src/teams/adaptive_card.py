from __future__ import annotations

import json
from typing import Any


def build_card(
    journal_id: int,
    issue_id: int,
    ticket_url: str,
    pattern_name: str,
    score: int,
    evidence: list[str],
    box_links: list[str],
) -> dict[str, Any]:
    """Teams Adaptive Card を構築する。"""
    evidence_text = "\n".join(f"- {e}" for e in evidence[:5]) or "(none)"
    box_text = "\n".join(box_links) if box_links else "(なし)"

    work_payload = _decision_payload(
        journal_id, issue_id, ticket_url, pattern_name, score, box_links, "work"
    )
    skip_payload = _decision_payload(
        journal_id, issue_id, ticket_url, pattern_name, score, box_links, "skip"
    )

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": f"[Redmine] Issue #{issue_id} / Journal #{journal_id}",
                "weight": "Bolder",
                "size": "Medium",
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "パターン", "value": pattern_name},
                    {"title": "スコア", "value": f"{score}/100"},
                ],
            },
            {
                "type": "TextBlock",
                "text": "**根拠 (Evidence):**",
                "weight": "Bolder",
            },
            {
                "type": "TextBlock",
                "text": evidence_text,
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": f"**チケット:** [{ticket_url}]({ticket_url})",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": f"**Box リンク:**\n{box_text}",
                "wrap": True,
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "作業する",
                "data": work_payload,
                "style": "positive",
            },
            {
                "type": "Action.Submit",
                "title": "作業しない",
                "data": skip_payload,
            },
        ],
    }


def _decision_payload(
    journal_id: int,
    issue_id: int,
    ticket_url: str,
    matched_pattern: str,
    score: int,
    box_links: list[str],
    decision: str,
) -> dict[str, Any]:
    return {
        "type": "decision",
        "journal_id": journal_id,
        "issue_id": issue_id,
        "ticket_url": ticket_url,
        "matched_pattern": matched_pattern,
        "score": score,
        "box_links": box_links,
        "decision": decision,
    }
