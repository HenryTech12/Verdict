"""Deterministic evidence scoring. The checklist score is the backbone of win likelihood;
the LLM may only nudge it within a bounded range (settings.llm_adjustment_limit)."""
from dataclasses import dataclass

from app.config import settings

REASON_NOT_RECEIVED = "ITEM_NOT_RECEIVED"
REASON_NOT_AS_DESCRIBED = "NOT_AS_DESCRIBED"
CONFLICT_ADDRESS = "Tracking says delivered but delivery address does not match the order address"
CONFLICT_LISTING = "Order record shows the shipped item does not match the listing the customer bought"


@dataclass(frozen=True)
class CaseEvidence:
    delivered: bool
    address_match: bool
    proof: bool
    communication_strength: float
    policy_accepted: bool
    fetch_failures: int = 0
    reason: str = REASON_NOT_RECEIVED
    matches_listing: bool = True
    pack_photo: bool = False


def _checklist(e: CaseEvidence) -> list[tuple[str, bool, float, float, str]]:
    """(type, present, weight, strength-if-present, note)"""
    comm = e.communication_strength
    if e.reason == REASON_NOT_AS_DESCRIBED:
        return [
            ("TRACKING_DELIVERED", e.delivered, 0.20, 1.0, "Carrier tracking status"),
            ("ITEM_MATCHES_LISTING", e.matches_listing, 0.35, 1.0, "Shipped item compared with the listing"),
            ("PACKING_PHOTO", e.pack_photo, 0.20, 1.0, "Pre-shipment photo of the packed item"),
            ("POLICY_ACCEPTED", e.policy_accepted, 0.15, 1.0, "Return and shipping policy acceptance on order"),
            ("CUSTOMER_COMMUNICATION", comm > 0, 0.10, comm, "Merchant message history"),
        ]
    return [
        ("TRACKING_DELIVERED", e.delivered, 0.30, 1.0, "Carrier tracking status"),
        ("ADDRESS_MATCH", e.address_match, 0.30, 1.0, "Delivery address compared with order address"),
        ("DELIVERY_PROOF", e.proof, 0.20, 1.0, "Signature or delivery photo"),
        ("CUSTOMER_COMMUNICATION", comm > 0, 0.10, comm, "Merchant message history"),
        ("POLICY_ACCEPTED", e.policy_accepted, 0.10, 1.0, "Shipping policy acceptance on order"),
    ]


def deterministic_conflicts(e: CaseEvidence) -> list[str]:
    if e.reason == REASON_NOT_AS_DESCRIBED:
        return [CONFLICT_LISTING] if e.delivered and not e.matches_listing else []
    return [CONFLICT_ADDRESS] if e.delivered and not e.address_match else []


def assess(evidence: CaseEvidence, llm_win_likelihood: float, llm_confidence: float, adjustment_limit: float | None = None) -> dict:
    limit = settings.llm_adjustment_limit if adjustment_limit is None else adjustment_limit
    items = _checklist(evidence)
    evidence_items = [
        {"type": kind, "present": present, "strength": round(strength, 2) if present else 0, "note": note}
        for kind, present, _weight, strength, note in items
    ]
    checklist_score = sum(weight * (strength if present else 0.0) for _kind, present, weight, strength, _note in items)
    conflicts = deterministic_conflicts(evidence)
    adjustment = max(-limit, min(limit, llm_win_likelihood - checklist_score))
    win_likelihood = min(1.0, max(0.0, checklist_score + adjustment))
    if conflicts:
        win_likelihood = min(win_likelihood, 0.25)
    confidence = max(0.0, min(1.0, llm_confidence - 0.15 * evidence.fetch_failures))
    return {
        "evidence_items": evidence_items,
        "conflicts": conflicts,
        "checklist_score": checklist_score,
        "llm_adjustment": adjustment,
        "win_likelihood": win_likelihood,
        "confidence": confidence,
    }
