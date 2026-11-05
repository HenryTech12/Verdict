"""Guardrails are code, not prompts: these tests pin every rule, the precedence order and the
'downgrade only' property."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import product

import pytest

from app.services.guardrails import RANK, apply_guardrails, is_expired, is_urgent


def g(decision="FIGHT", amount="80", expired=False, confidence=0.9, conflicts=None, **kw):
    return apply_guardrails(decision, Decimal(amount), expired, confidence, conflicts or [], **kw)


def test_no_guardrail_when_everything_is_clean():
    assert g("FIGHT") == ("FIGHT", None)
    assert g("REFUND", "90") == ("REFUND", None)


def test_amount_above_approval_threshold_escalates_any_action():
    assert g("FIGHT", "480") == ("ESCALATE", "AMOUNT_ABOVE_APPROVAL_THRESHOLD")
    assert g("REFUND", "250.01") == ("ESCALATE", "AMOUNT_ABOVE_APPROVAL_THRESHOLD")
    assert g("FIGHT", "250") == ("FIGHT", None)  # exactly at the threshold does not trigger it


def test_refund_cap_boundary():
    assert g("REFUND", "100") == ("REFUND", None)
    assert g("REFUND", "100.01") == ("ESCALATE", "REFUND_ABOVE_AUTO_REFUND_CAP")
    assert g("FIGHT", "180") == ("FIGHT", None)  # the cap applies to refunds only


def test_conflicts_block_fight_but_not_a_conflict_driven_refund():
    assert g("FIGHT", conflicts=["x"]) == ("ESCALATE", "CONFLICTING_EVIDENCE")
    assert g("REFUND", "90", conflicts=["Tracking address mismatch"]) == ("REFUND", None)


def test_low_confidence_and_missing_evidence():
    assert g("FIGHT", confidence=0.69) == ("ESCALATE", "LOW_CONFIDENCE")
    assert g("REFUND", missing_evidence=True) == ("ESCALATE", "MISSING_EVIDENCE")


def test_expired_deadline_beats_every_other_rule():
    assert g("FIGHT", "480", expired=True, conflicts=["x"], missing_evidence=True) == ("EXPIRED", "DEADLINE_EXPIRED")


def test_precedence_threshold_before_cap_before_confidence_before_conflict():
    assert g("REFUND", "480", confidence=0.1, conflicts=["x"])[1] == "AMOUNT_ABOVE_APPROVAL_THRESHOLD"
    assert g("REFUND", "120", confidence=0.1, conflicts=["x"])[1] == "REFUND_ABOVE_AUTO_REFUND_CAP"
    assert g("FIGHT", "80", confidence=0.1, conflicts=["x"])[1] == "LOW_CONFIDENCE"


def test_custom_limits_are_respected():
    assert g("REFUND", "60", auto_refund_cap=Decimal("50")) == ("ESCALATE", "REFUND_ABOVE_AUTO_REFUND_CAP")
    assert g("FIGHT", "120", approval_threshold=Decimal("100")) == ("ESCALATE", "AMOUNT_ABOVE_APPROVAL_THRESHOLD")


@pytest.mark.parametrize("decision,amount,expired,confidence,conflicts,missing", list(product(["FIGHT", "REFUND", "ESCALATE"], ["10", "100", "101", "250", "251", "900"], [False, True], [0.1, 0.7, 0.99], [[], ["x"]], [False, True])))
def test_guardrails_never_upgrade_an_action(decision, amount, expired, confidence, conflicts, missing):
    final, _rule = g(decision, amount, expired, confidence, conflicts, missing_evidence=missing)
    assert RANK[final] <= RANK[decision]
    if decision == "ESCALATE":
        assert final in ("ESCALATE", "EXPIRED")


def test_deadline_helpers():
    now = datetime.now(timezone.utc)
    assert is_expired(now - timedelta(minutes=1))
    assert not is_expired(now + timedelta(minutes=1))
    assert is_urgent(now + timedelta(hours=23))
    assert not is_urgent(now + timedelta(hours=25))
    assert not is_urgent(now - timedelta(hours=1))
    assert is_expired((now - timedelta(hours=1)).replace(tzinfo=None))  # naive datetimes from SQLite are treated as UTC
