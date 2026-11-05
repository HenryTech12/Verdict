from datetime import datetime, timedelta, timezone
from decimal import Decimal
from random import Random

from app.db import Base, SessionLocal, engine
from app.models import Assessment, Approval, AuditLog, Decision, Dispute, Merchant, Message, Order, Shipment
from app.services.assessment import assess
from app.services.guardrails import apply_guardrails
from app.services.policy import choose_policy_with_rule, lean_action
from app.services.scenarios import case_data


def seed() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    random = Random(42)
    merchant = db.query(Merchant).first() or Merchant(name="Verdict Demo Merchant", settings_json={})
    db.add(merchant)
    db.flush()
    for index in range(120):
        created = datetime.now(timezone.utc) - timedelta(days=random.randrange(90), hours=random.randrange(24))
        amount = Decimal(str(random.choice([39, 65, 80, 90, 120, 180, 280, 480])))
        order_id = f"HIST-ORD-{index:04d}"
        db.add(Order(id=order_id, merchant_id=merchant.id, customer_name=f"Historical customer {index + 1}", amount=amount, items_json=[{"name": "Demo item", "qty": 1, "price": str(amount)}], ship_address="12 Allen Ave, Ikeja", policy_accepted=random.random() > 0.08, paypal_capture_id=f"HIST-CAP-{index:04d}"))
        conflict = random.random() < 0.16
        db.add(Shipment(order_id=order_id, tracking=f"HIST-{index:08d}", status="DELIVERED", delivered_at=created + timedelta(days=1), delivery_address="5 Marina Rd, Lagos" if conflict else "12 Allen Ave, Ikeja", proof_url="SIMULATED proof" if random.random() > 0.2 else None))
        db.add(Message(order_id=order_id, sender="customer", text="SIMULATED historical customer message"))
        dispute = Dispute(id=f"HIST-DSP-{index:04d}", paypal_dispute_id=f"HIST-PP-{index:04d}", order_id=order_id, amount=amount, deadline=created + timedelta(days=14), created_at=created, case="H", simulated=True)
        db.add(dispute)
        db.flush()
        evidence = case_data("B")["evidence"] if conflict else case_data("A")["evidence"]
        result = assess(evidence, random.uniform(0.35, 0.98), random.uniform(0.72, 0.98))
        policy, rule_fired = choose_policy_with_rule(result["win_likelihood"], result["confidence"])
        action, rule = apply_guardrails(policy, amount, False, result["confidence"], result["conflicts"])
        status = {"FIGHT": "EVIDENCE_SUBMITTED", "REFUND": "REFUNDED", "ESCALATE": "RESOLVED", "EXPIRED": "EXPIRED"}[action]
        result.update({"recommended": policy, "rationale": "SIMULATED historical assessment", "packet_draft": "SIMULATED historical packet"})
        db.add(Assessment(dispute_id=dispute.id, evidence_json=result["evidence_items"], conflicts_json=result["conflicts"], checklist_score=result["checklist_score"], win_likelihood=result["win_likelihood"], confidence=result["confidence"], recommended=policy, rationale=result["rationale"], packet_draft=result["packet_draft"]))
        db.add(Decision(dispute_id=dispute.id, policy_decision=policy, rule_fired=rule_fired, guardrail_rule=rule, final_action=action))
        if action == "ESCALATE":
            db.add(Approval(dispute_id=dispute.id, requested_action=lean_action(result["win_likelihood"]), recommendation_summary="SIMULATED historical recommendation reviewed", status="REJECTED", decided_at=created + timedelta(days=2)))
        dispute.status = status
        dispute.resolved_at = created + timedelta(days=2)
        db.add(AuditLog(dispute_id=dispute.id, step="LOG", summary="SIMULATED historical case recorded", simulated=True))
    db.commit()
    db.close()
    print("Seeded 120 simulated historical disputes.")


if __name__ == "__main__":
    seed()