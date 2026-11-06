"""Seeded demo scenarios. Cases A, B and C are the PRD acceptance tests; D, E and F exercise the
second reason code, the urgent-deadline flag and the expired-deadline rule."""
from dataclasses import dataclass
from decimal import Decimal

from app.services.assessment import REASON_NOT_AS_DESCRIBED, REASON_NOT_RECEIVED, CaseEvidence

PAYPAL_REASONS = {
    REASON_NOT_RECEIVED: "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
    REASON_NOT_AS_DESCRIBED: "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED",
}
REASON_FROM_PAYPAL = {value: key for key, value in PAYPAL_REASONS.items()}


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    customer: str
    amount: Decimal
    reason: str = REASON_NOT_RECEIVED
    ship_address: str = "12 Allen Ave, Ikeja"
    delivery_address: str = "12 Allen Ave, Ikeja"
    proof: bool = True
    policy_accepted: bool = True
    deadline_hours: float = 12 * 24
    matches_listing: bool = True
    pack_photo: bool = False
    item: str = "Wireless Mouse"
    expected: str = "FIGHT"
    customer_message: str = "I have not received this order."
    merchant_message: str = "Carrier tracking and delivery proof are available."


SCENARIOS: dict[str, Scenario] = {
    "A": Scenario("A", "Easy fight", "Ada Obi", Decimal("80.00"), expected="FIGHT"),
    "B": Scenario("B", "Conflict: delivered to a different address", "Tunde A.", Decimal("90.00"), delivery_address="5 Marina Rd, Lagos", expected="REFUND"),
    "C": Scenario("C", "High value needs approval", "Mina Okafor", Decimal("480.00"), expected="ESCALATE"),
    "D": Scenario("D", "Not as described, strong packing proof", "Chidi Eze", Decimal("70.00"), reason=REASON_NOT_AS_DESCRIBED, pack_photo=True, item="Ceramic Mug Set", customer_message="The mugs are not what the listing showed.", expected="FIGHT"),
    "E": Scenario("E", "Urgent: approval needed, 6 hours left", "Ngozi Bello", Decimal("300.00"), deadline_hours=6, expected="ESCALATE"),
    "F": Scenario("F", "Expired deadline: no action", "Femi Ade", Decimal("55.00"), deadline_hours=-2, expected="EXPIRED"),
}


def scenario_evidence(s: Scenario) -> CaseEvidence:
    return CaseEvidence(
        delivered=True,
        address_match=s.ship_address == s.delivery_address,
        proof=s.proof,
        communication_strength=1.0,
        policy_accepted=s.policy_accepted,
        reason=s.reason,
        matches_listing=s.matches_listing,
        pack_photo=s.pack_photo,
    )


def case_data(case: str) -> dict:
    """Backward-compatible helper used by the historical seeder."""
    s = SCENARIOS[case]
    return {"customer_name": s.customer, "amount": s.amount, "evidence": scenario_evidence(s)}
