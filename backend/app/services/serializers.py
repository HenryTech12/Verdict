from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Approval, Assessment, AuditLog, Decision, Dispute, Order, Shipment
from app.services.guardrails import as_utc, is_urgent

TERMINAL = {"EVIDENCE_SUBMITTED", "REFUNDED", "RESOLVED", "EXPIRED"}


def _row(dispute: Dispute, order: Order | None, assessment: Assessment | None, decision: Decision | None) -> dict:
    return {
        "id": dispute.id,
        "paypal_dispute_id": dispute.paypal_dispute_id,
        "customer_name": order.customer_name if order else "Unknown",
        "amount": dispute.amount,
        "currency": dispute.currency,
        "reason": dispute.reason,
        "status": dispute.status,
        "deadline": as_utc(dispute.deadline),
        "win_likelihood": assessment.win_likelihood if assessment else None,
        "confidence": assessment.confidence if assessment else None,
        "decision": decision.final_action if decision else None,
        "policy_decision": decision.policy_decision if decision else None,
        "guardrail_rule": decision.guardrail_rule if decision else None,
        "urgent": dispute.status not in TERMINAL and is_urgent(dispute.deadline),
        "simulated": dispute.simulated,
        "created_at": as_utc(dispute.created_at),
    }


def serialize_many(db: Session, disputes: list[Dispute]) -> list[dict]:
    if not disputes:
        return []
    ids = [d.id for d in disputes]
    orders = {o.id: o for o in db.scalars(select(Order).where(Order.id.in_([d.order_id for d in disputes])))}
    assessments = {a.dispute_id: a for a in db.scalars(select(Assessment).where(Assessment.dispute_id.in_(ids)))}
    decisions = {d.dispute_id: d for d in db.scalars(select(Decision).where(Decision.dispute_id.in_(ids)))}
    return [_row(d, orders.get(d.order_id), assessments.get(d.id), decisions.get(d.id)) for d in disputes]


def serialize_dispute(db: Session, dispute: Dispute) -> dict:
    return serialize_many(db, [dispute])[0]


def dispute_detail(db: Session, dispute: Dispute) -> dict:
    order = db.get(Order, dispute.order_id)
    shipment = db.get(Shipment, dispute.order_id)
    assessment = db.scalar(select(Assessment).where(Assessment.dispute_id == dispute.id))
    decision = db.scalar(select(Decision).where(Decision.dispute_id == dispute.id))
    approval = db.scalar(select(Approval).where(Approval.dispute_id == dispute.id))
    audit = db.scalars(select(AuditLog).where(AuditLog.dispute_id == dispute.id).order_by(AuditLog.id)).all()
    return {
        **serialize_dispute(db, dispute),
        "order": order and {"id": order.id, "items": order.items_json, "ship_address": order.ship_address, "policy_accepted": order.policy_accepted, "paypal_capture_id": order.paypal_capture_id},
        "shipment": shipment and {"carrier": shipment.carrier, "tracking": shipment.tracking, "status": shipment.status, "delivered_at": shipment.delivered_at, "delivery_address": shipment.delivery_address, "proof_url": shipment.proof_url},
        "assessment": assessment and {"evidence_items": assessment.evidence_json, "conflicts": assessment.conflicts_json, "checklist_score": assessment.checklist_score, "win_likelihood": assessment.win_likelihood, "confidence": assessment.confidence, "recommended": assessment.recommended, "rationale": assessment.rationale, "packet_draft": assessment.packet_draft, "llm_error": assessment.llm_error, "token_usage": assessment.token_usage},
        "decision": decision and {"policy_decision": decision.policy_decision, "rule_fired": decision.rule_fired, "guardrail_rule": decision.guardrail_rule, "final_action": decision.final_action},
        "approval": approval and {"requested_action": approval.requested_action, "status": approval.status, "decided_by": approval.decided_by, "note": approval.note, "decided_at": approval.decided_at},
        "audit": [{"id": a.id, "step": a.step, "summary": a.summary, "input": a.input_json, "output": a.output_json, "simulated": a.simulated, "duration_ms": a.duration_ms, "ts": as_utc(a.ts)} for a in audit],
    }
