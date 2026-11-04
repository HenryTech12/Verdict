import asyncio
import json
from contextlib import asynccontextmanager
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, engine, ensure_compat_schema, get_db
from app.models import Action, Assessment, Approval, AuditLog, Decision, Dispute, Merchant, Message, Order, Shipment, WebhookEvent
from app.schemas import ApprovalItem, DisputeListResponse, Health, SettingsSchema, SimulationResponse
from app.services.assessment import CaseEvidence, assess
from app.services.events import event_bus
from app.services.guardrails import apply_guardrails
from app.services.policy import choose_policy
from app.services.pipeline import evaluate_case, execute_action
from app.adapters.paypal_real import SandboxPayPalAdapter

@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    ensure_compat_schema()
    yield


app = FastAPI(title="Verdict API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin, "http://127.0.0.1:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
ai_requests: deque[float] = deque()


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) and "error" in exc.detail else {"error": {"code": "INTERNAL_ERROR", "message": str(exc.detail), "details": {}}}
    return JSONResponse(status_code=exc.status_code, content=detail)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_ERROR", "message": "Request validation failed", "details": {"errors": exc.errors()}}})


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


def settings_for(db: Session) -> SettingsSchema:
    merchant = db.scalar(select(Merchant))
    stored = merchant.settings_json if merchant else {}
    return SettingsSchema(auto_refund_cap=Decimal(str(stored.get("auto_refund_cap", settings.auto_refund_cap))), approval_threshold=Decimal(str(stored.get("approval_threshold", settings.approval_threshold))), fight_min_win_likelihood=float(stored.get("fight_min_win_likelihood", settings.fight_min_win_likelihood)), refund_max_win_likelihood=float(stored.get("refund_max_win_likelihood", settings.refund_max_win_likelihood)), min_confidence=float(stored.get("min_confidence", settings.min_confidence)), shipping_policy_text=str(stored.get("shipping_policy_text", "Orders ship within 2 business days.")))


@app.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", paypal_mode=settings.paypal_mode, llm_provider=settings.llm_provider, version="1.0.0")


@app.post("/sim/dispute", response_model=SimulationResponse, status_code=201, dependencies=[Depends(require_token)])
def simulate(case: str = Query(pattern="^[ABC]$"), db: Session = Depends(get_db)) -> SimulationResponse:
    data = case_data(case)
    merchant = db.scalar(select(Merchant))
    if not merchant:
        merchant = Merchant(name="Verdict Demo Merchant", settings_json={"shipping_policy_text": "Orders ship within 2 business days."})
        db.add(merchant)
        db.flush()
    order_id = f"ORD-{uuid4().hex[:8].upper()}"
    order = Order(id=order_id, merchant_id=merchant.id, customer_name=data["customer_name"], amount=data["amount"], items_json=[{"name": "Wireless Mouse", "qty": 1, "price": str(data["amount"])}], ship_address=data["ship_address"], policy_accepted=data["policy_accepted"], paypal_capture_id=f"CAP-{uuid4().hex[:8].upper()}")
    db.add(order)
    db.add(Shipment(order_id=order_id, tracking=f"SIM-{uuid4().hex[:10].upper()}", status="DELIVERED", delivered_at=datetime.now(timezone.utc) - timedelta(days=2), delivery_address=data["delivery_address"], proof_url=data["proof_url"]))
    db.add(Message(order_id=order_id, sender="customer", text="I have not received this order."))
    db.add(Message(order_id=order_id, sender="merchant", text="Carrier tracking and delivery proof are available."))
    dispute_id = f"DSP-{uuid4().hex[:6].upper()}"
    dispute = Dispute(id=dispute_id, paypal_dispute_id=f"PP-D-{uuid4().hex[:8].upper()}", order_id=order_id, amount=data["amount"], deadline=datetime.now(timezone.utc) + timedelta(days=12), case=case, simulated=True)
    db.add(dispute)
    db.flush()
    db.add(AuditLog(dispute_id=dispute_id, step="INGEST", summary="SIMULATED dispute received", simulated=True))
    merchant_settings = settings_for(db)
    outcome = asyncio.run(evaluate_case(data["evidence"], data["amount"], False, {"fight_min_win_likelihood": merchant_settings.fight_min_win_likelihood, "refund_max_win_likelihood": merchant_settings.refund_max_win_likelihood, "min_confidence": merchant_settings.min_confidence, "approval_threshold": merchant_settings.approval_threshold, "auto_refund_cap": merchant_settings.auto_refund_cap}))
    result = outcome["assessment"]
    recommendation = outcome["recommendation"]
    final_action = outcome["final_action"]
    rule = outcome["guardrail_rule"]
    status = {"FIGHT": "EVIDENCE_SUBMITTED", "REFUND": "REFUNDED", "ESCALATE": "AWAITING_APPROVAL", "EXPIRED": "EXPIRED"}[final_action]
    result.update({"recommended": recommendation, "rationale": data["rationale"], "packet_draft": f"SIMULATED evidence packet for {dispute_id}."})
    db.add(Assessment(dispute_id=dispute_id, evidence_json=result["evidence_items"], conflicts_json=result["conflicts"], checklist_score=result["checklist_score"], win_likelihood=result["win_likelihood"], confidence=result["confidence"], recommended=recommendation, rationale=result["rationale"], packet_draft=result["packet_draft"]))
    db.add(Decision(dispute_id=dispute_id, policy_decision=recommendation, guardrail_rule=rule, final_action=final_action))
    if final_action in {"FIGHT", "REFUND"}:
        action_result = asyncio.run(execute_action(dispute_id, final_action, order.paypal_capture_id, data["amount"], order.currency, result["packet_draft"]))
        db.add(Action(dispute_id=dispute_id, action_type=final_action, idempotency_key=f"{dispute_id}:{final_action}", result_json=action_result, simulated=bool(action_result["simulated"])))
    if final_action == "ESCALATE":
        db.add(Approval(dispute_id=dispute_id, requested_action=recommendation, recommendation_summary=result["rationale"], status="PENDING"))
    dispute.status = status
    for step in ("GATHER", "ASSESS", "DECIDE", "GUARD", "ACT", "LOG"):
        db.add(AuditLog(dispute_id=dispute_id, step=step, summary=f"{step.title()} completed", simulated=True, output_json={"final_action": final_action, "guardrail_rule": rule, "llm_error": result.get("llm_error")}, duration_ms=settings.stage_delay_ms))
    db.commit()
    event_bus.publish("dispute_created", {"dispute": serialize_dispute(db, dispute)})
    return SimulationResponse(dispute_id=dispute_id, case=case, simulated=True)


@app.get("/disputes", response_model=DisputeListResponse, dependencies=[Depends(require_token)])
def list_disputes(db: Session = Depends(get_db), page: int = 1, page_size: int = 50) -> DisputeListResponse:
    disputes = db.scalars(select(Dispute).order_by(Dispute.created_at.desc())).all()
    items = [serialize_dispute(db, dispute) for dispute in disputes]
    return DisputeListResponse(items=items[(page - 1) * page_size:page * page_size], total=len(items), page=page, page_size=page_size)


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


@app.get("/approvals", response_model=list[ApprovalItem], dependencies=[Depends(require_token)])
def list_approvals(db: Session = Depends(get_db), status: str = "PENDING") -> list[ApprovalItem]:
    approvals = db.scalars(select(Approval).where(Approval.status == status).order_by(Approval.created_at)).all()
    return [ApprovalItem(id=item.id, dispute_id=item.dispute_id, requested_action=item.requested_action, recommendation_summary=item.recommendation_summary, status=item.status, created_at=item.created_at) for item in approvals]


@app.post("/disputes/{dispute_id}/approve", dependencies=[Depends(require_token)])
def approve(dispute_id: str, db: Session = Depends(get_db)) -> dict:
    dispute = db.get(Dispute, dispute_id)
    approval = db.scalar(select(Approval).where(Approval.dispute_id == dispute_id, Approval.status == "PENDING"))
    if not dispute or not approval:
        raise HTTPException(status_code=409, detail={"error": {"code": "ALREADY_PROCESSED", "message": "Approval is no longer pending", "details": {}}})
    deadline = dispute.deadline.replace(tzinfo=timezone.utc) if dispute.deadline.tzinfo is None else dispute.deadline
    if deadline < datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail={"error": {"code": "GUARDRAIL_BLOCKED", "message": "Dispute deadline has expired", "details": {}}})
    approval.status = "APPROVED"
    approval.decided_at = datetime.now(timezone.utc)
    dispute.status = "EVIDENCE_SUBMITTED" if approval.requested_action == "FIGHT" else "REFUNDED"
    dispute.resolved_at = datetime.now(timezone.utc)
    order = db.get(Order, dispute.order_id)
    assessment = db.scalar(select(Assessment).where(Assessment.dispute_id == dispute_id))
    action_result = asyncio.run(execute_action(dispute_id, approval.requested_action, order.paypal_capture_id, dispute.amount, dispute.currency, assessment.packet_draft if assessment else ""))
    db.add(Action(dispute_id=dispute_id, action_type=approval.requested_action, idempotency_key=f"{dispute_id}:{approval.requested_action}", result_json=action_result, simulated=bool(action_result["simulated"])))
    db.add(AuditLog(dispute_id=dispute_id, step="ACT", summary=f"Approval executed: {approval.requested_action}", simulated=True))
    db.commit()
    event_bus.publish("dispute_updated", {"dispute": serialize_dispute(db, dispute), "changed": ["status", "decision"]})
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
    dispute.resolved_at = datetime.now(timezone.utc)
    db.add(AuditLog(dispute_id=dispute_id, step="ACT", summary="Merchant rejected the recommendation; no action taken", simulated=True))
    db.commit()
    event_bus.publish("dispute_updated", {"dispute": serialize_dispute(db, dispute), "changed": ["status"]})
    return get_dispute(dispute_id, db)


@app.post("/webhooks/paypal")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    body = await request.body()
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail={"error": {"code": "VALIDATION_ERROR", "message": "Webhook body must be valid JSON", "details": {}}}) from error
    if settings.paypal_mode == "sandbox":
        try:
            verified = await SandboxPayPalAdapter().verify_webhook(dict(request.headers), body)
        except Exception as error:
            raise HTTPException(status_code=502, detail={"error": {"code": "UPSTREAM_ERROR", "message": "PayPal webhook verification failed", "details": {}}}) from error
        if not verified:
            raise HTTPException(status_code=401, detail={"error": {"code": "UNAUTHORIZED", "message": "PayPal webhook signature verification failed", "details": {}}})
    else:
        event_bus.publish("audit_added", {"dispute_id": "", "entry": {"step": "INGEST", "summary": "signature_skipped", "simulated": True}})
    event_id = str(payload.get("id", ""))
    event_type = str(payload.get("event_type", ""))
    if not event_id:
        raise HTTPException(status_code=422, detail={"error": {"code": "VALIDATION_ERROR", "message": "Webhook event id is required", "details": {}}})
    if db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == event_id)):
        return {"status": "duplicate"}
    db.add(WebhookEvent(event_id=event_id, event_type=event_type))
    db.commit()
    if event_type not in {"CUSTOMER.DISPUTE.CREATED", "CUSTOMER.DISPUTE.UPDATED", "CUSTOMER.DISPUTE.RESOLVED"}:
        return {"status": "ignored"}
    resource = payload.get("resource", {})
    paypal_dispute_id = str(resource.get("dispute_id", ""))
    local = db.scalar(select(Dispute).where(Dispute.paypal_dispute_id == paypal_dispute_id)) if paypal_dispute_id else None
    if local:
        if event_type == "CUSTOMER.DISPUTE.RESOLVED":
            local.status = "RESOLVED"
            local.resolved_at = datetime.now(timezone.utc)
        db.add(AuditLog(dispute_id=local.id, step="INGEST", summary="PayPal webhook received", simulated=False, input_json=payload))
        db.commit()
        event_bus.publish("dispute_updated", {"dispute": serialize_dispute(db, local), "changed": ["status"]})
        return {"status": "accepted", "dispute_id": local.id}
    merchant = db.scalar(select(Merchant)) or Merchant(name="PayPal Merchant", settings_json={})
    if merchant.id is None:
        db.add(merchant)
        db.flush()
    order_id = f"PAYPAL-ORDER-{uuid4().hex[:8].upper()}"
    amount_data = resource.get("dispute_amount", {})
    amount = Decimal(str(amount_data.get("value", "0")))
    currency = str(amount_data.get("currency_code", "USD"))
    db.add(Order(id=order_id, merchant_id=merchant.id, customer_name="PayPal customer", amount=amount, currency=currency, items_json=[], ship_address="Unknown", policy_accepted=False, paypal_capture_id=str(resource.get("disputed_transactions", [{}])[0].get("seller_transaction_id", ""))))
    placeholder_id = f"DSP-{uuid4().hex[:6].upper()}"
    dispute = Dispute(id=placeholder_id, paypal_dispute_id=paypal_dispute_id or f"EVENT-{event_id}", order_id=order_id, amount=amount, currency=currency, status="AWAITING_APPROVAL", deadline=datetime.now(timezone.utc) + timedelta(days=1), simulated=False)
    db.add(dispute)
    db.flush()
    db.add(AuditLog(dispute_id=placeholder_id, step="INGEST", summary="Real PayPal dispute received with incomplete local evidence", input_json=payload, output_json={"reason": "MISSING_EVIDENCE"}, simulated=False))
    db.add(Decision(dispute_id=placeholder_id, policy_decision="ESCALATE", guardrail_rule="MISSING_EVIDENCE", final_action="ESCALATE"))
    db.add(Approval(dispute_id=placeholder_id, requested_action="ESCALATE", recommendation_summary="Real webhook has no matching local order evidence.", status="PENDING"))
    db.commit()
    event_bus.publish("dispute_created", {"dispute": serialize_dispute(db, dispute)})
    return {"status": "accepted", "dispute_id": placeholder_id}


@app.get("/stream")
async def stream(token: str | None = None, last_event_id: int = Header(default=0, alias="Last-Event-ID")) -> StreamingResponse:
    if token != settings.api_token:
        raise HTTPException(status_code=401, detail={"error": {"code": "UNAUTHORIZED", "message": "Valid stream token required", "details": {}}})

    async def generate():
        cursor = last_event_id
        while True:
            events = event_bus.after(cursor)
            for event in events:
                cursor = event.id
                yield f"id: {event.id}\nevent: {event.name}\ndata: {json.dumps(event.data, default=str)}\n\n"
            await asyncio.sleep(15)
            yield ": heartbeat\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@app.post("/ai/proxy", dependencies=[Depends(require_token)])
async def ai_proxy(request: Request) -> JSONResponse:
    if settings.llm_provider != "groq" or not settings.groq_api_key:
        raise HTTPException(status_code=502, detail={"error": {"code": "UPSTREAM_ERROR", "message": "Groq is not configured", "details": {}}})
    body = await request.body()
    if len(body) > 100_000:
        raise HTTPException(status_code=422, detail={"error": {"code": "VALIDATION_ERROR", "message": "AI request is too large", "details": {"max_bytes": 100000}}})
    now = time.monotonic()
    while ai_requests and now - ai_requests[0] > 60:
        ai_requests.popleft()
    if len(ai_requests) >= 20:
        raise HTTPException(status_code=429, detail={"error": {"code": "UPSTREAM_ERROR", "message": "AI rate limit exceeded", "details": {"limit": 20, "window_seconds": 60}}})
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail={"error": {"code": "VALIDATION_ERROR", "message": "AI request must be JSON", "details": {}}}) from error
    payload["model"] = settings.llm_model
    ai_requests.append(now)
    import httpx
    async with httpx.AsyncClient(timeout=settings.llm_timeout_s) as client:
        response = await client.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"}, json=payload)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail={"error": {"code": "UPSTREAM_ERROR", "message": "Groq request failed", "details": {"status": response.status_code}}})
    return JSONResponse(status_code=response.status_code, content=response.json())


@app.get("/settings", response_model=SettingsSchema, dependencies=[Depends(require_token)])
def get_settings(db: Session = Depends(get_db)) -> SettingsSchema:
    return settings_for(db)


@app.put("/settings", response_model=SettingsSchema, dependencies=[Depends(require_token)])
def update_settings(payload: SettingsSchema, db: Session = Depends(get_db)) -> SettingsSchema:
    merchant = db.scalar(select(Merchant))
    if not merchant:
        merchant = Merchant(name="Verdict Demo Merchant", settings_json={})
        db.add(merchant)
    merchant.settings_json = {"auto_refund_cap": str(payload.auto_refund_cap), "approval_threshold": str(payload.approval_threshold), "fight_min_win_likelihood": payload.fight_min_win_likelihood, "refund_max_win_likelihood": payload.refund_max_win_likelihood, "min_confidence": payload.min_confidence, "shipping_policy_text": payload.shipping_policy_text}
    db.commit()
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
    for table in (Action, WebhookEvent, AuditLog, Approval, Decision, Assessment, Message, Dispute, Shipment, Order, Merchant):
        db.query(table).delete()
    db.commit()
    from seed import seed
    seed()
    return {"status": "reset", "seeded": True}


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
