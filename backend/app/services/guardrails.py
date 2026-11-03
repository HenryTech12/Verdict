from decimal import Decimal


def apply_guardrails(decision: str, amount: Decimal, deadline_expired: bool, confidence: float, conflicts: list[str], approval_threshold: Decimal = Decimal("250"), auto_refund_cap: Decimal = Decimal("100"), min_confidence: float = 0.70) -> tuple[str, str | None]:
    if deadline_expired:
        return "EXPIRED", "DEADLINE_EXPIRED"
    if amount > approval_threshold:
        return "ESCALATE", "AMOUNT_ABOVE_APPROVAL_THRESHOLD"
    if decision == "REFUND" and amount > auto_refund_cap:
        return "ESCALATE", "REFUND_ABOVE_AUTO_REFUND_CAP"
    if confidence < min_confidence:
        return "ESCALATE", "LOW_CONFIDENCE"
    if decision == "FIGHT" and conflicts:
        return "ESCALATE", "CONFLICTING_EVIDENCE"
    return decision, None
