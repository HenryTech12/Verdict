from decimal import Decimal

import pytest

from app.config import settings
from app.services.assessment import CaseEvidence, assess
from app.services.guardrails import apply_guardrails, is_expired, is_urgent
from app.services.policy import choose_policy, choose_policy_with_rule
from datetime import datetime, timedelta, timezone

GOOD = CaseEvidence(True, True, True, 1.0, True)
CONFLICT = CaseEvidence(True, False, True, 1.0, True)


def test_conflict_caps_win_likelihood():
    result = assess(CONFLICT, 0.95, 0.86)
    assert result["conflicts"]
    assert result["win_likelihood"] <= 0.25


def test_llm_can_only_nudge_the_checklist_score():
    strong = assess(GOOD, 0.0, 0.9)  # a pessimistic model cannot drag a perfect checklist below 1 - limit
    assert strong["win_likelihood"] == pytest.approx(1.0 - settings.llm_adjustment_limit)
    weak = assess(CaseEvidence(False, False, False, 0.0, False), 1.0, 0.9)  # an optimistic model cannot rescue an empty case
    assert weak["win_likelihood"] == pytest.approx(settings.llm_adjustment_limit)


def test_fetch_failures_lower_confidence():
    assert assess(GOOD, 0.9, 0.9)["confidence"] > assess(CaseEvidence(True, True, True, 1.0, True, fetch_failures=2), 0.9, 0.9)["confidence"]


def test_second_reason_code_has_its_own_checklist():
    nad = CaseEvidence(True, True, False, 1.0, True, reason="NOT_AS_DESCRIBED", matches_listing=True, pack_photo=True)
    types = {item["type"] for item in assess(nad, 0.85, 0.86)["evidence_items"]}
    assert "ITEM_MATCHES_LISTING" in types and "ADDRESS_MATCH" not in types
    mismatch = CaseEvidence(True, True, False, 1.0, True, reason="NOT_AS_DESCRIBED", matches_listing=False)
    assert assess(mismatch, 0.9, 0.9)["conflicts"]


@pytest.mark.parametrize("win,conf,expected,rule", [
    (0.60, 0.70, "FIGHT", "FIGHT_THRESHOLD"),
    (0.59, 0.70, "ESCALATE", "UNCERTAIN_BAND_DEFAULT"),
    (0.35, 0.70, "ESCALATE", "UNCERTAIN_BAND_DEFAULT"),
    (0.34, 0.70, "REFUND", "REFUND_THRESHOLD"),
    (0.90, 0.69, "ESCALATE", "LOW_CONFIDENCE_DEFAULT"),
    (0.10, 0.69, "ESCALATE", "LOW_CONFIDENCE_DEFAULT"),
])
def test_policy_boundaries_and_rule_fired(win, conf, expected, rule):
    assert choose_policy_with_rule(win, conf) == (expected, rule)
    assert choose_policy(win, conf) == expected


def test_settings_schema_defaults_are_valid():
    assert settings.auto_refund_cap > 0
    assert settings.approval_threshold > settings.auto_refund_cap
