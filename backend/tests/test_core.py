from decimal import Decimal

from app.services.assessment import CaseEvidence, assess
from app.services.guardrails import apply_guardrails
from app.services.policy import choose_policy
from app.config import settings


def test_conflict_caps_win_likelihood():
    result = assess(CaseEvidence(True, False, True, 1.0, True), 0.95, 0.86)
    assert result["conflicts"]
    assert result["win_likelihood"] <= 0.25


def test_policy_boundaries():
    assert choose_policy(0.60, 0.70) == "FIGHT"
    assert choose_policy(0.35, 0.70) == "ESCALATE"
    assert choose_policy(0.34, 0.70) == "REFUND"
    assert choose_policy(0.90, 0.69) == "ESCALATE"


def test_guardrails_downgrade_only():
    assert apply_guardrails("FIGHT", Decimal("480"), False, 0.9, []) == ("ESCALATE", "AMOUNT_ABOVE_APPROVAL_THRESHOLD")
    assert apply_guardrails("REFUND", Decimal("101"), False, 0.9, []) == ("ESCALATE", "REFUND_ABOVE_AUTO_REFUND_CAP")
    assert apply_guardrails("FIGHT", Decimal("80"), False, 0.9, ["mismatch"]) == ("ESCALATE", "CONFLICTING_EVIDENCE")
    assert apply_guardrails("FIGHT", Decimal("80"), True, 0.9, []) == ("EXPIRED", "DEADLINE_EXPIRED")


def test_settings_schema_defaults_are_valid():
    assert settings.auto_refund_cap > 0
    assert settings.approval_threshold > settings.auto_refund_cap
