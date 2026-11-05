import asyncio
import json
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters import get_adapter
from app.adapters.paypal_mock import MockPayPalAdapter
from app.config import settings
from app.db import Base, SessionLocal, engine, ensure_compat_schema, get_db
from app.models import Action, Approval, Assessment, AuditLog, Decision, Dispute, Merchant, Message, Order, Shipment, WebhookEvent
from app.schemas import ApprovalActionBody, ApprovalItem, DisputeListResponse, Health, SettingsSchema, SimulationResponse
from app.services import pipeline
from app.services.errors import RuleError
from app.services.events import event_bus
from app.services.ingest import ingest
from app.services.merchant import save_settings, settings_for
from app.services.metrics import impact_metrics
from app.services.scenarios import SCENARIOS
from app.services.serializers import dispute_detail, serialize_many
from app.services.simulator import fire_simulated_dispute


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    ensure_compat_schema()
    if settings.auto_seed:
        with SessionLocal() as db:
            if not db.scalar(select(func.count()).select_from(Dispute)):
                from seed import seed

                seed()
    yield


app = FastAPI(title="Verdict API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin, "http://127.0.0.1:3000", "http://localhost:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
ai_requests: deque[float] = deque()


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) and "error" in exc.detail else error_body("INTERNAL_ERROR", str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content=detail)


@app.exception_handler(RuleError)
async def rule_error_handler(_request: Request, exc: RuleError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=error_body(exc.code, exc.message, exc.details))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content=error_body("VALIDATION_ERROR", "Request validation failed", {"errors": json.loads(json.dumps(exc.errors(), default=str))}))


def require_token(authorization: str | None = Header(default=None)) -> None:
    if authorization != f"Bearer {settings.api_token}":
        raise HTTPException(status_code=401, detail=error_body("UNAUTHORIZED", "Valid bearer token required"))


@app.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", paypal_mode=settings.paypal_mode, llm_provider=settings.llm_provider, version="1.0.0")


# ------------------------------------------------------------------ webhooks + simulator

@app.post("/webhooks/paypal")
async def paypal_webhook(request: Request, background: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    body = await request.body()
    adapter = get_adapter()
    try:
        # Webhooks from our own simulator carry an HMAC signed with WEBHOOK_SIM_SECRET and are accepted in any mode;
        # everything else must pass the active adapter's check (PayPal's signature verification in sandbox mode).
        verified = await MockPayPalAdapter().verify_webhook(dict(request.headers), body) or await adapter.verify_webhook(dict(request.headers), body)
    except Exception as error:  # a verification outage must never accept an unverified event
        raise HTTPException(status_code=401, detail=error_body("UNAUTHORIZED", "Webhook signature could not be verified", {"reason": type(error).__name__})) from error
    if not verified:
        raise HTTPException(status_code=401, detail=error_body("UNAUTHORIZED", "Invalid webhook signature"))
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise RuleError("INVALID_WEBHOOK", "Webhook body must be JSON", 422) from error
    outcome = await ingest(db, payload)
    if outcome.pop("run", False):
        background.add_task(pipeline.run_pipeline, outcome["dispute_id"])
    return outcome


@app.post("/sim/dispute", response_model=SimulationResponse, status_code=201, dependencies=[Depends(require_token)])
async def simulate(case: str = Query(default="A", pattern="^[A-F]$"), db: Session = Depends(get_db)) -> SimulationResponse:
    try:
        dispute_id = await fire_simulated_dispute(app, db, case)
    except TimeoutError as error:
        raise HTTPException(status_code=504, detail=error_body("UPSTREAM_ERROR", str(error))) from error
    return SimulationResponse(dispute_id=dispute_id, case=case, simulated=True)


@app.get("/sim/cases", dependencies=[Depends(require_token)])
def simulator_cases() -> list[dict]:
    return [{"case": s.key, "title": s.title, "amount": str(s.amount), "reason": s.reason, "expected": s.expected, "deadline_hours": s.deadline_hours} for s in SCENARIOS.values()]


# ------------------------------------------------------------------ disputes

@app.get("/disputes", response_model=DisputeListResponse, dependencies=[Depends(require_token)])
def list_disputes(db: Session = Depends(get_db), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500), status: str | None = None, decision: str | None = None, search: str | None = None, sort: str = "created_at", order: str = "desc") -> DisputeListResponse:
    query = select(Dispute)
    if status:
        query = query.where(Dispute.status == status)
    if search:
        like = f"%{search}%"
        query = query.join(Order, Order.id == Dispute.order_id).where((Dispute.id.ilike(like)) | (Dispute.paypal_dispute_id.ilike(like)) | (Order.customer_name.ilike(like)))
    column = {"created_at": Dispute.created_at, "deadline": Dispute.deadline, "amount": Dispute.amount, "status": Dispute.status}.get(sort, Dispute.created_at)
    query = query.order_by(column.asc() if order == "asc" else column.desc())
    rows = serialize_many(db, list(db.scalars(query).all()))
    if decision:
        rows = [row for row in rows if row["decision"] == decision]
    return DisputeListResponse(items=rows[(page - 1) * page_size:page * page_size], total=len(rows), page=page, page_size=page_size)


@app.get("/disputes/{dispute_id}", dependencies=[Depends(require_token)])
def get_dispute(dispute_id: str, db: Session = Depends(get_db)) -> dict:
    dispute = db.get(Dispute, dispute_id)
    if not dispute:
        raise HTTPException(status_code=404, detail=error_body("DISPUTE_NOT_FOUND", "Dispute not found"))
    return dispute_detail(db, dispute)


@app.get("/disputes/{dispute_id}/packet", dependencies=[Depends(require_token)])
def download_packet(dispute_id: str, db: Session = Depends(get_db)) -> PlainTextResponse:
    assessment = db.scalar(select(Assessment).where(Assessment.dispute_id == dispute_id))
    if not assessment:
        raise HTTPException(status_code=404, detail=error_body("DISPUTE_NOT_FOUND", "No evidence packet for this dispute yet"))
    return PlainTextResponse(assessment.packet_draft, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="verdict-packet-{dispute_id}.md"'})


@app.get("/approvals", response_model=list[ApprovalItem], dependencies=[Depends(require_token)])
def list_approvals(db: Session = Depends(get_db), status: str = "PENDING") -> list[ApprovalItem]:
    items = []
    for approval in db.scalars(select(Approval).where(Approval.status == status).order_by(Approval.created_at)).all():
        dispute = db.get(Dispute, approval.dispute_id)
        items.append(ApprovalItem(id=approval.id, dispute_id=approval.dispute_id, requested_action=approval.requested_action, recommendation_summary=approval.recommendation_summary, amount=dispute.amount if dispute else None, deadline=dispute.deadline if dispute else None, status=approval.status, created_at=approval.created_at))
    items.sort(key=lambda item: (item.deadline is None, item.deadline))  # soonest deadline first
    return items


@app.post("/disputes/{dispute_id}/approve", dependencies=[Depends(require_token)])
async def approve(dispute_id: str, body: ApprovalActionBody | None = None, db: Session = Depends(get_db)) -> dict:
    dispute = await pipeline.approve(db, dispute_id, body.note if body else None, override_action=body.action if body else None)
    return dispute_detail(db, dispute)


@app.post("/disputes/{dispute_id}/reject", dependencies=[Depends(require_token)])
def reject(dispute_id: str, body: ApprovalActionBody | None = None, db: Session = Depends(get_db)) -> dict:
    dispute = pipeline.reject(db, dispute_id, body.note if body else None)
    return dispute_detail(db, dispute)


# ------------------------------------------------------------------ live stream

@app.get("/stream")
async def stream(request: Request, token: str | None = None, last_event_id: int = Header(default=0, alias="Last-Event-ID")) -> StreamingResponse:
    if token != settings.api_token:
        raise HTTPException(status_code=401, detail=error_body("UNAUTHORIZED", "Valid stream token required"))

    async def generate():
        cursor, last_beat = last_event_id, time.monotonic()
        yield "retry: 2000\n\n"
        while not await request.is_disconnected():
            for event in event_bus.after(cursor):
                cursor = event.id
                yield f"id: {event.id}\nevent: {event.name}\ndata: {json.dumps(event.data, default=str)}\n\n"
            if time.monotonic() - last_beat > 15:
                last_beat = time.monotonic()
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.3)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


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
    return save_settings(db, payload)  # per-merchant row only; process-wide defaults are never mutated


@app.get("/metrics", dependencies=[Depends(require_token)])
def metrics(db: Session = Depends(get_db)) -> dict:
    return impact_metrics(db)


@app.post("/seed/reset", dependencies=[Depends(require_token)])
def reset_seed(db: Session = Depends(get_db)) -> dict:
    for table in (Action, WebhookEvent, AuditLog, Approval, Decision, Assessment, Message, Dispute, Shipment, Order, Merchant):
        db.query(table).delete()
    db.commit()
    from seed import seed

    seed()
    event_bus.publish("metrics_updated", {})
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
    return [{"dispute_id": row.dispute_id, "step": row.step, "summary": row.summary, "simulated": row.simulated, "duration_ms": row.duration_ms, "ts": row.ts, "day": row.ts.date().isoformat()} for row in db.scalars(select(AuditLog).order_by(AuditLog.ts)).all()]


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
        daily["modeled_revenue_recovered"] += row["amount_value"] * row["win_likelihood"] if row["status"] == "EVIDENCE_SUBMITTED" else 0
        daily["modeled_hours_saved"] += settings.modeled_minutes_per_case / 60 if row["status"] in ("REFUNDED", "EVIDENCE_SUBMITTED", "RESOLVED", "EXPIRED") else 0
    return list(by_day.values())


@app.get("/analytics/schema", dependencies=[Depends(require_token)])
def analytics_schema() -> dict:
    return {"sources": {"disputes": {"fields": {"id": "string", "amount_value": "number", "status": "category", "decision": "category", "win_likelihood": "number", "created_at": "temporal", "deadline": "temporal"}}, "evidence": {"fields": {"dispute_id": "string", "evidence_type": "category", "present": "boolean", "strength": "number"}}, "audit": {"fields": {"dispute_id": "string", "step": "category", "duration_ms": "number", "ts": "temporal"}}, "guardrails": {"fields": {"dispute_id": "string", "rule": "category", "outcome": "category"}}, "daily": {"fields": {"day": "temporal", "disputes_opened": "number", "modeled_revenue_recovered": "number", "modeled_hours_saved": "number"}}}}
