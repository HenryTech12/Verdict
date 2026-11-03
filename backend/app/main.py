from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, engine, get_db
from app.models import Assessment, Approval, AuditLog, Decision, Dispute, Merchant, Order, Shipment
from app.schemas import DisputeListItem, Health, SettingsSchema
from app.services.assessment import CaseEvidence, assess
from app.services.guardrails import apply_guardrails
from app.services.policy import choose_policy

app = FastAPI(title="Verdict API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup() -> None:
    Path("backend").mkdir(exist_ok=True)
    Base.metadata.create_all(engine)


def require_token(authorization: str | None = Header(default=None)) -> None:
    if authorization != f"Bearer {settings.api_token}":
        raise HTTPException(status_code=401, detail={"error": {"code": "UNAUTHORIZED", "message": "Valid bearer token required", "details": {}}})


def case_data(case: str) -> dict:
    common = {"customer_name": "Ada Obi", "ship_address": "12 Allen Ave, Ikeja", "policy_accepted": True, "proof_url": "SIMULATED delivery-photo.jpg"}
    if case == "B":
        return {**common, "customer_name": "Tunde A.", "amount": Decimal("90.00"), "delivery_address": "5 Marina Rd, Lagos", "evidence": CaseEvidence(True, False, True, 1.0, True), "llm_win": 0.55, "rationale": "Agent chose not to fight: tracking shows delivery to a different address."}
    if case == "C":
        return {**common, "customer_name": "Mina Okafor", "amount": Decimal("480.00"), "delivery_address": common["ship_address"], "evidence": CaseEvidence(True, True, True, 1.0, True), "llm_win": 0.95, "rationale": "Strong delivery evidence supports fighting the dispute."}
    return {**common, "amount": Decimal("80.00"), "delivery_address": common["ship_address"], "evidence": CaseEvidence(True, True, True, 1.0, True), "llm_win": 0.95, "rationale": "Delivered shipment, matching address, proof, and messages support fighting."}


def serialize_dispute(db: Session, dispute: Dispute) -> dict:
    order = db.get(Order, dispute.order_id)
    assessment = db.scalar(select(Assessment).where(Assessment.dispute_id == dispute.id))
    decision = db.scalar(select(Decision).where(Decision.dispute_id == dispute.id))
    return {"id": dispute.id, "paypal_dispute_id": dispute.paypal_dispute_id, "customer_name": order.customer_name, "amount": dispute.amount, "currency": dispute.currency, "reason": dispute.reason, "status": dispute.status, "deadline": dispute.deadline, "win_likelihood": assessment.win_likelihood if assessment else None, "confidence": assessment.confidence if assessment else None, "decision": decision.final_action if decision else None, "simulated": dispute.simulated, "created_at": dispute.created_at}


@app.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", paypal_mode=settings.paypal_mode, llm_provider=settings.llm_provider, version="1.0.0")


@app.post("/sim/dispute", status_code=201, dependencies=[Depends(require_token)])
def simulate(case: str = Query(pattern="^[ABC]$"), db: Session = Depends(get_db)) -> dict:
    data = case_data(case)
    duplicate = db.scalar(select(Dispute).where(Dispute.case == case, Dispute.simulated.is_(True)))
    if duplicate:
        return {"dispute_id": duplicate.id, "case": case, "simulated": True}
    merchant = db.scalar(select(Merchant))
    if not merchant:
        merchant = Merchant(name="Verdict Demo Merchant", settings_json={"shipping_policy_text": "Orders ship within 2 business days."})
        db.add(merchant)
        db.flush()
    order_id = f"ORD-{uuid4().hex[:8].upper()}"
    order = Order(id=order_id, merchant_id=merchant.id, customer_name=data["customer_name"], amount=data["amount"], items_json=[{"name": "Wireless Mouse", "qty": 1, "price": str(data["amount"])}], ship_address=data["ship_address"], policy_accepted=data["policy_accepted"], paypal_capture_id=f"CAP-{uuid4().hex[:8].upper()}")
    db.add(order)
    db.add(Shipment(order_id=order_id, tracking=f"SIM-{uuid4().hex[:10].upper()}", status="DELIVERED", delivered_at=datetime.now(timezone.utc) - timedelta(days=2), delivery_address=data["delivery_address"], proof_url=data["proof_url"]))
    dispute_id = f"DSP-{uuid4().hex[:6].upper()}"
    dispute = Dispute(id=dispute_id, paypal_dispute_id=f"PP-D-{uuid4().hex[:8].upper()}", order_id=order_id, amount=data["amount"], deadline=datetime.now(timezone.utc) + timedelta(days=12), case=case, simulated=True)
    db.add(dispute)
    db.flush()
    db.add(AuditLog(dispute_id=dispute_id, step="INGEST", summary="SIMULATED dispute received", simulated=True))
    result = assess(data["evidence"], data["llm_win"], 0.86)
    recommendation = choose_policy(result["win_likelihood"], result["confidence"], settings.fight_min_win_likelihood, settings.refund_max_win_likelihood, settings.min_confidence)
    final_action, rule = apply_guardrails(recommendation, data["amount"], False, result["confidence"], result["conflicts"], settings.approval_threshold, settings.auto_refund_cap, settings.min_confidence)
    status = {"FIGHT": "EVIDENCE_SUBMITTED", "REFUND": "REFUNDED", "ESCALATE": "AWAITING_APPROVAL", "EXPIRED": "EXPIRED"}[final_action]
    result.update({"recommended": recommendation, "rationale": data["rationale"], "packet_draft": f"SIMULATED evidence packet for {dispute_id}."})
    db.add(Assessment(dispute_id=dispute_id, evidence_json=result["evidence_items"], conflicts_json=result["conflicts"], checklist_score=result["checklist_score"], win_likelihood=result["win_likelihood"], confidence=result["confidence"], recommended=recommendation, rationale=result["rationale"], packet_draft=result["packet_draft"]))
    db.add(Decision(dispute_id=dispute_id, policy_decision=recommendation, guardrail_rule=rule, final_action=final_action))
    if final_action == "ESCALATE":
        db.add(Approval(dispute_id=dispute_id, requested_action=recommendation, recommendation_summary=result["rationale"], status="PENDING"))
    dispute.status = status
    for step in ("GATHER", "ASSESS", "DECIDE", "GUARD", "ACT", "LOG"):
        db.add(AuditLog(dispute_id=dispute_id, step=step, summary=f"{step.title()} completed", simulated=True, output_json={"final_action": final_action, "guardrail_rule": rule}))
    db.commit()
    return {"dispute_id": dispute_id, "case": case, "simulated": True}


@app.get("/disputes", dependencies=[Depends(require_token)])
def list_disputes(db: Session = Depends(get_db), page: int = 1, page_size: int = 50) -> dict:
    disputes = db.scalars(select(Dispute).order_by(Dispute.created_at.desc())).all()
    items = [serialize_dispute(db, dispute) for dispute in disputes]
    return {"items": items[(page - 1) * page_size:page * page_size], "total": len(items), "page": page, "page_size": page_size}


@app.get("/disputes/{dispute_id}", dependencies=[Depends(require_token)])
def get_dispute(dispute_id: str, db: Session = Depends(get_db)) -> dict:
    dispute = db.get(Dispute, dispute_id)
    if not dispute:
        raise HTTPException(status_code=404, detail={"error": {"code": "DISPUTE_NOT_FOUND", "message": "Dispute not found", "details": {}}})
    order = db.get(Order, dispute.order_id)
    shipment = db.get(Shipment, dispute.order_id)
    assessment = db.scalar(select(Assessment).where(Assessment.dispute_id == dispute.id))
    decision = db.scalar(select(Decision).where(Decision.dispute_id == dispute.id))
    audit = db.scalars(select(AuditLog).where(AuditLog.dispute_id == dispute.id).order_by(AuditLog.id)).all()
    return {**serialize_dispute(db, dispute), "order": {"id": order.id, "items": order.items_json, "ship_address": order.ship_address, "policy_accepted": order.policy_accepted, "paypal_capture_id": order.paypal_capture_id}, "shipment": {"carrier": shipment.carrier, "tracking": shipment.tracking, "status": shipment.status, "delivered_at": shipment.delivered_at, "delivery_address": shipment.delivery_address, "proof_url": shipment.proof_url}, "assessment": assessment and {"evidence_items": assessment.evidence_json, "conflicts": assessment.conflicts_json, "checklist_score": assessment.checklist_score, "win_likelihood": assessment.win_likelihood, "confidence": assessment.confidence, "recommended": assessment.recommended, "rationale": assessment.rationale, "packet_draft": assessment.packet_draft}, "decision": decision and {"policy_decision": decision.policy_decision, "guardrail_rule": decision.guardrail_rule, "final_action": decision.final_action}, "audit": [{"id": item.id, "step": item.step, "summary": item.summary, "input": item.input_json, "output": item.output_json, "simulated": item.simulated, "ts": item.ts} for item in audit]}


@app.get("/approvals", dependencies=[Depends(require_token)])
def list_approvals(db: Session = Depends(get_db), status: str = "PENDING") -> list[dict]:
    approvals = db.scalars(select(Approval).where(Approval.status == status).order_by(Approval.created_at)).all()
    return [{"id": item.id, "dispute_id": item.dispute_id, "requested_action": item.requested_action, "recommendation_summary": item.recommendation_summary, "status": item.status, "created_at": item.created_at} for item in approvals]


@app.post("/disputes/{dispute_id}/approve", dependencies=[Depends(require_token)])
def approve(dispute_id: str, db: Session = Depends(get_db)) -> dict:
    dispute = db.get(Dispute, dispute_id)
    approval = db.scalar(select(Approval).where(Approval.dispute_id == dispute_id, Approval.status == "PENDING"))
    if not dispute or not approval:
        raise HTTPException(status_code=409, detail={"error": {"code": "ALREADY_PROCESSED", "message": "Approval is no longer pending", "details": {}}})
    if dispute.deadline < datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail={"error": {"code": "GUARDRAIL_BLOCKED", "message": "Dispute deadline has expired", "details": {}}})
    approval.status = "APPROVED"
    approval.decided_at = datetime.now(timezone.utc)
    dispute.status = "EVIDENCE_SUBMITTED" if approval.requested_action == "FIGHT" else "REFUNDED"
    db.add(AuditLog(dispute_id=dispute_id, step="ACT", summary=f"Approval executed: {approval.requested_action}", simulated=True))
    db.commit()
    return get_dispute(dispute_id, db)


@app.post("/disputes/{dispute_id}/reject", dependencies=[Depends(require_token)])
def reject(dispute_id: str, db: Session = Depends(get_db)) -> dict:
    dispute = db.get(Dispute, dispute_id)
    approval = db.scalar(select(Approval).where(Approval.dispute_id == dispute_id, Approval.status == "PENDING"))
    if not dispute or not approval:
        raise HTTPException(status_code=409, detail={"error": {"code": "ALREADY_PROCESSED", "message": "Approval is no longer pending", "details": {}}})
    approval.status = "REJECTED"
    approval.decided_at = datetime.now(timezone.utc)
    dispute.status = "RESOLVED"
    db.add(AuditLog(dispute_id=dispute_id, step="ACT", summary="Merchant rejected the recommendation; no action taken", simulated=True))
    db.commit()
    return get_dispute(dispute_id, db)


@app.get("/settings", response_model=SettingsSchema, dependencies=[Depends(require_token)])
def get_settings() -> SettingsSchema:
    return SettingsSchema(auto_refund_cap=settings.auto_refund_cap, approval_threshold=settings.approval_threshold, fight_min_win_likelihood=settings.fight_min_win_likelihood, refund_max_win_likelihood=settings.refund_max_win_likelihood, min_confidence=settings.min_confidence, shipping_policy_text="Orders ship within 2 business days.")


@app.put("/settings", response_model=SettingsSchema, dependencies=[Depends(require_token)])
def update_settings(payload: SettingsSchema) -> SettingsSchema:
    settings.auto_refund_cap = payload.auto_refund_cap
    settings.approval_threshold = payload.approval_threshold
    settings.fight_min_win_likelihood = payload.fight_min_win_likelihood
    settings.refund_max_win_likelihood = payload.refund_max_win_likelihood
    settings.min_confidence = payload.min_confidence
    return payload


@app.get("/metrics", dependencies=[Depends(require_token)])
def metrics(db: Session = Depends(get_db)) -> dict:
    disputes = db.scalars(select(Dispute)).all()
    fought = sum((item.amount for item in disputes if item.status == "EVIDENCE_SUBMITTED"), Decimal("0"))
    return {"disputes_handled": len(disputes), "auto_resolved": sum(item.status in ("REFUNDED", "EVIDENCE_SUBMITTED", "RESOLVED") for item in disputes), "escalated": sum(item.status == "AWAITING_APPROVAL" for item in disputes), "refunds_issued": sum(item.status == "REFUNDED" for item in disputes), "evidence_submitted": sum(item.status == "EVIDENCE_SUBMITTED" for item in disputes), "modeled_revenue_recovered": str(fought), "modeled_hours_saved": round(len(disputes) * 0.4, 1), "assumptions": {"minutes_per_manual_case": 25, "recovered_counts_only_fought_cases_marked_resolved_won": True}}


@app.post("/seed/reset", dependencies=[Depends(require_token)])
def reset_seed(db: Session = Depends(get_db)) -> dict:
    for table in (AuditLog, Approval, Decision, Assessment, Dispute, Shipment, Order, Merchant):
        db.query(table).delete()
    db.commit()
    return {"status": "reset"}


def analytics_rows(db: Session) -> list[dict]:
    disputes = db.scalars(select(Dispute).order_by(Dispute.created_at)).all()
    rows = []
    for dispute in disputes:
        order = db.get(Order, dispute.order_id)
        assessment = db.scalar(select(Assessment).where(Assessment.dispute_id == dispute.id))
        decision = db.scalar(select(Decision).where(Decision.dispute_id == dispute.id))
        deadline = dispute.deadline.replace(tzinfo=timezone.utc) if dispute.deadline.tzinfo is None else dispute.deadline
        hours = (deadline - datetime.now(timezone.utc)).total_seconds() / 3600
        created = dispute.created_at.date().isoformat()
        rows.append({"id": dispute.id, "paypal_dispute_id": dispute.paypal_dispute_id, "customer_name": order.customer_name, "amount_value": float(dispute.amount), "currency": dispute.currency, "reason": dispute.reason, "status": dispute.status, "decision": decision.policy_decision if decision else None, "final_action": decision.final_action if decision else None, "win_likelihood": assessment.win_likelihood if assessment else 0, "confidence": assessment.confidence if assessment else 0, "checklist_score": assessment.checklist_score if assessment else 0, "has_conflict": bool(assessment and assessment.conflicts_json), "conflict_summary": (assessment.conflicts_json[0] if assessment and assessment.conflicts_json else None), "guardrail_rule": decision.guardrail_rule if decision else None, "simulated": dispute.simulated, "created_at": dispute.created_at, "deadline": deadline, "hours_to_deadline": round(hours, 2), "resolved_at": dispute.created_at if dispute.status in ("REFUNDED", "EVIDENCE_SUBMITTED", "RESOLVED") else None, "day": created, "week": f"{dispute.created_at.isocalendar().year}-W{dispute.created_at.isocalendar().week:02d}"})
    return rows


@app.get("/analytics/disputes", dependencies=[Depends(require_token)])
def analytics_disputes(db: Session = Depends(get_db)) -> list[dict]:
    return analytics_rows(db)


@app.get("/analytics/evidence", dependencies=[Depends(require_token)])
def analytics_evidence(db: Session = Depends(get_db)) -> list[dict]:
    rows = []
    for dispute in db.scalars(select(Dispute)).all():
        assessment = db.scalar(select(Assessment).where(Assessment.dispute_id == dispute.id))
        decision = db.scalar(select(Decision).where(Decision.dispute_id == dispute.id))
        for item in (assessment.evidence_json if assessment else []):
            rows.append({"dispute_id": dispute.id, "evidence_type": item["type"], "present": item["present"], "strength": item["strength"], "decision": decision.policy_decision if decision else None, "status": dispute.status, "created_at": dispute.created_at})
    return rows


@app.get("/analytics/audit", dependencies=[Depends(require_token)])
def analytics_audit(db: Session = Depends(get_db)) -> list[dict]:
    return [{"dispute_id": row.dispute_id, "step": row.step, "summary": row.summary, "simulated": row.simulated, "duration_ms": settings.stage_delay_ms, "ts": row.ts, "day": row.ts.date().isoformat()} for row in db.scalars(select(AuditLog).order_by(AuditLog.ts)).all()]


@app.get("/analytics/guardrails", dependencies=[Depends(require_token)])
def analytics_guardrails(db: Session = Depends(get_db)) -> list[dict]:
    return [{"dispute_id": row.dispute_id, "rule": row.guardrail_rule, "outcome": "downgraded_to_escalate", "simulated": True} for row in db.scalars(select(Decision).where(Decision.guardrail_rule.is_not(None))).all()]


@app.get("/analytics/daily", dependencies=[Depends(require_token)])
def analytics_daily(db: Session = Depends(get_db)) -> list[dict]:
    rows = analytics_rows(db)
    by_day: dict[str, dict] = {}
    for row in rows:
        daily = by_day.setdefault(row["day"], {"day": row["day"], "disputes_opened": 0, "disputes_resolved": 0, "refunds_issued": 0, "evidence_submitted": 0, "escalated": 0, "modeled_revenue_recovered": 0.0, "modeled_hours_saved": 0.0})
        daily["disputes_opened"] += 1
        daily["disputes_resolved"] += row["status"] in ("REFUNDED", "EVIDENCE_SUBMITTED", "RESOLVED")
        daily["refunds_issued"] += row["status"] == "REFUNDED"
        daily["evidence_submitted"] += row["status"] == "EVIDENCE_SUBMITTED"
        daily["escalated"] += row["status"] == "AWAITING_APPROVAL"
        daily["modeled_revenue_recovered"] += row["amount_value"] if row["final_action"] == "FIGHT" else 0
        daily["modeled_hours_saved"] += 0.4
    return list(by_day.values())


@app.get("/analytics/schema", dependencies=[Depends(require_token)])
def analytics_schema() -> dict:
    return {"sources": {"disputes": {"fields": {"id": "string", "amount_value": "number", "status": "category", "decision": "category", "win_likelihood": "number", "created_at": "temporal", "deadline": "temporal"}}, "evidence": {"fields": {"dispute_id": "string", "evidence_type": "category", "present": "boolean", "strength": "number"}}, "audit": {"fields": {"dispute_id": "string", "step": "category", "duration_ms": "number", "ts": "temporal"}}, "guardrails": {"fields": {"dispute_id": "string", "rule": "category", "outcome": "category"}}, "daily": {"fields": {"day": "temporal", "disputes_opened": "number", "modeled_revenue_recovered": "number", "modeled_hours_saved": "number"}}}}
