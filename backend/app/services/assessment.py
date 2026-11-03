from dataclasses import dataclass


@dataclass(frozen=True)
class CaseEvidence:
    delivered: bool
    address_match: bool
    proof: bool
    communication_strength: float
    policy_accepted: bool
    fetch_failures: int = 0


def assess(evidence: CaseEvidence, llm_win_likelihood: float, llm_confidence: float) -> dict:
    items = [
        ("TRACKING_DELIVERED", evidence.delivered, 0.30, "Carrier tracking status"),
        ("ADDRESS_MATCH", evidence.address_match, 0.30, "Delivery address compared with order address"),
        ("DELIVERY_PROOF", evidence.proof, 0.20, "Signature or delivery photo"),
        ("CUSTOMER_COMMUNICATION", evidence.communication_strength > 0, 0.10, "Merchant message history"),
        ("POLICY_ACCEPTED", evidence.policy_accepted, 0.10, "Shipping policy acceptance on order"),
    ]
    evidence_items = [{"type": kind, "present": present, "strength": strength if present else 0, "note": note} for kind, present, strength, note in items]
    checklist_score = sum(weight * (evidence.communication_strength if kind == "CUSTOMER_COMMUNICATION" else float(present)) for kind, present, weight, _ in items)
    conflicts = []
    if evidence.delivered and not evidence.address_match:
        conflicts.append("Tracking says delivered but delivery address does not match the order address")
    win_likelihood = min(1.0, max(0.0, 0.7 * checklist_score + 0.3 * llm_win_likelihood))
    if conflicts:
        win_likelihood = min(win_likelihood, 0.25)
    confidence = max(0.0, llm_confidence - 0.15 * evidence.fetch_failures)
    return {"evidence_items": evidence_items, "conflicts": conflicts, "checklist_score": checklist_score, "win_likelihood": win_likelihood, "confidence": confidence}
