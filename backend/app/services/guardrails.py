"""Guardrails run after the model and before any action. They can downgrade a decision
to ESCALATE (or stop it as EXPIRED) but never upgrade one. Prompt text is not a guardrail."""
from datetime import datetime, timezone
from decimal import Decimal

from app.config import settings

RANK = {"EXPIRED": 0, "ESCALATE": 1, "REFUND": 2, "FIGHT": 2}


def apply_guardrails(
    decision: str,
    amount: Decimal,
    deadline_expired: bool,
    confidence: float,
    conflicts: list[str],
    approval_threshold: Decimal = Decimal("250"),
    auto_refund_cap: Decimal = Decimal("100"),
    min_confidence: float = 0.70,
    missing_evidence: bool = False,
    missing_deadline: bool = False,
) -> tuple[str, str | None]:
    """Precedence: expired > missing evidence > approval threshold > refund cap > low confidence > conflicting evidence."""
    if deadline_expired:
        return "EXPIRED", "DEADLINE_EXPIRED"
    if missing_evidence:
        return "ESCALATE", "MISSING_EVIDENCE"
    if missing_deadline:
        return "ESCALATE", "DEADLINE_MISSING"
    if amount > approval_threshold:
        return "ESCALATE", "AMOUNT_ABOVE_APPROVAL_THRESHOLD"
    if decision == "REFUND" and amount > auto_refund_cap:
        return "ESCALATE", "REFUND_ABOVE_AUTO_REFUND_CAP"
    if confidence < min_confidence:
        return "ESCALATE", "LOW_CONFIDENCE"
    if decision == "FIGHT" and conflicts:
        return "ESCALATE", "CONFLICTING_EVIDENCE"
    return decision, None



def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def hours_until(
    deadline: datetime | None,
    now: datetime | None = None,
) -> float | None:
    deadline_utc = as_utc(deadline)
    if deadline_utc is None:
        return None

    return (
        deadline_utc - (now or datetime.now(timezone.utc))
    ).total_seconds() / 3600


def is_expired(
    deadline: datetime | None,
    now: datetime | None = None,
) -> bool:
    hours = hours_until(deadline, now)
    return hours is not None and hours <= 0


def is_urgent(
    deadline: datetime | None,
    now: datetime | None = None,
    urgent_hours: int | None = None,
) -> bool:
    hours = hours_until(deadline, now)
    if hours is None:
        return False

    return 0 < hours < (
        settings.urgent_hours if urgent_hours is None else urgent_hours
    )