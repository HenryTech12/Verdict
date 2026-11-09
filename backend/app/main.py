import asyncio
import json
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
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
from app.services.simulator import fire_simulated_dispute, seed_store_data
import uuid
import httpx
from app.services.merchant import get_merchant


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


class PayPalOrderBody(BaseModel):
    amount: float = Field(gt=0, le=5000)
    currency: str = Field(default="USD", pattern="^USD$")



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



@app.post("/orders/register-capture", status_code=201, dependencies=[Depends(require_token)])
async def register_real_capture(
    capture_id: str = Query(min_length=5, max_length=64),
    paypal_order_id: str = Query(min_length=5, max_length=64),
    db: Session = Depends(get_db),
) -> dict:
    """Register a real PayPal capture using verified payment data only."""

    if settings.paypal_mode != "sandbox":
        raise RuleError(
            "PAYPAL_MODE_REQUIRED",
            "Real capture registration requires PayPal sandbox mode.",
            409,
        )

    existing = db.scalar(
        select(Order).where(Order.paypal_capture_id == capture_id)
    )
    if existing:
        raise RuleError(
            "ALREADY_PROCESSED",
            "An order with this capture ID already exists.",
        )

    adapter = get_adapter()

    try:
        capture = await adapter.get_capture(capture_id)
    except httpx.HTTPStatusError as error:
        raise RuleError(
            "PAYPAL_CAPTURE_VERIFICATION_FAILED",
            f"PayPal rejected capture verification (HTTP {error.response.status_code}).",
            502,
        ) from error
    except httpx.HTTPError as error:
        raise RuleError(
            "PAYPAL_CAPTURE_VERIFICATION_FAILED",
            "Could not communicate with PayPal to verify the capture.",
            502,
        ) from error


    try:
        paypal_order = await adapter.get_order(paypal_order_id)
    except httpx.HTTPStatusError as error:
        raise RuleError(
            "PAYPAL_ORDER_VERIFICATION_FAILED",
            f"PayPal rejected order verification (HTTP {error.response.status_code}).",
            502,
        ) from error
    except httpx.HTTPError as error:
        raise RuleError(
            "PAYPAL_ORDER_VERIFICATION_FAILED",
            "Could not communicate with PayPal to verify the checkout order.",
            502,
        ) from error

    if paypal_order.get("id") != paypal_order_id:
        raise RuleError(
            "PAYPAL_ORDER_MISMATCH",
            "PayPal returned a different checkout order.",
            422,
        )

    if paypal_order.get("status") != "COMPLETED":
        raise RuleError(
            "PAYPAL_ORDER_NOT_COMPLETED",
            "The supplied PayPal checkout order is not completed.",
            409,
        )

    if capture.get("id") != capture_id:
        raise RuleError(
            "CAPTURE_ID_MISMATCH",
            "PayPal returned a different capture ID.",
            422,
        )

    if capture.get("status") != "COMPLETED":
        raise RuleError(
            "CAPTURE_NOT_COMPLETED",
            f"PayPal capture status is {capture.get('status', 'UNKNOWN')}.",
            409,
        )

    amount_data = capture.get("amount") or {}

    try:
        amount = Decimal(str(amount_data["value"]))
        currency = str(amount_data["currency_code"]).upper()
    except (KeyError, ValueError, ArithmeticError):
        raise RuleError(
            "INVALID_CAPTURE_AMOUNT",
            "PayPal returned an invalid capture amount.",
            422,
        )

    if amount <= 0 or len(currency) != 3:
        raise RuleError(
            "INVALID_CAPTURE_AMOUNT",
            "PayPal returned an invalid amount or currency.",
            422,
        )

        # Check the relationship independently using PayPal's checkout order.
    related_ids = (
        (capture.get("supplementary_data") or {}).get("related_ids") or {}
    )
    related_order_id = related_ids.get("order_id")

    if related_order_id and related_order_id != paypal_order_id:
        raise RuleError(
            "PAYPAL_ORDER_MISMATCH",
            "The capture does not belong to the supplied PayPal order.",
            422,
        )

    matching_capture = None

    for purchase_unit in paypal_order.get("purchase_units") or []:
        payments = purchase_unit.get("payments") or {}

        for order_capture in payments.get("captures") or []:
            if order_capture.get("id") == capture_id:
                matching_capture = order_capture
                break

        if matching_capture:
            break

    if not matching_capture:
        raise RuleError(
            "PAYPAL_ORDER_MISMATCH",
            "The supplied PayPal order does not contain this capture.",
            422,
        )

    if matching_capture.get("status") != "COMPLETED":
        raise RuleError(
            "CAPTURE_NOT_COMPLETED",
            "The capture in the PayPal order is not completed.",
            409,
        )

    order_capture_amount = matching_capture.get("amount") or {}

    try:
        order_amount = Decimal(str(order_capture_amount["value"]))
        order_currency = str(order_capture_amount["currency_code"]).upper()
    except (KeyError, ValueError, ArithmeticError):
        raise RuleError(
            "INVALID_CAPTURE_AMOUNT",
            "PayPal returned invalid capture details in the checkout order.",
            422,
        )

    if order_amount != amount or order_currency != currency:
        raise RuleError(
            "CAPTURE_DETAILS_MISMATCH",
            "The capture amount or currency does not match the checkout order.",
            422,
        )

    order = Order(
        id=f"ORD-{uuid.uuid4().hex[:8].upper()}",
        merchant_id=get_merchant(db).id,
        customer_name="Unknown customer",
        amount=amount,
        currency=currency,
        items_json=[],
        ship_address="Not provided",
        policy_accepted=False,
        paypal_capture_id=capture_id,
    )

    db.add(order)
    db.commit()

    return {
        "order_id": order.id,
        "capture_id": capture_id,
        "paypal_order_id": paypal_order_id,
        "amount": str(amount),
        "currency": currency,
        "status": capture["status"],
        "simulated": False,
    }



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
    """Narrow, server-controlled Groq proxy for AG Studio. Client payloads never choose model,
    token budget, streaming mode, or arbitrary upstream request fields."""
    if settings.llm_provider != "groq" or not settings.groq_api_key:
        raise HTTPException(status_code=502, detail=error_body("UPSTREAM_ERROR", "Groq is not configured"))
    body = await request.body()
    if len(body) > 100_000:
        raise HTTPException(status_code=422, detail=error_body("VALIDATION_ERROR", "AI request is too large", {"max_bytes": 100000}))
    try:
        incoming = json.loads(body or b"{}")
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail=error_body("VALIDATION_ERROR", "AI request must be JSON")) from error
    if not isinstance(incoming, dict) or not isinstance(incoming.get("messages"), list):
        raise HTTPException(status_code=422, detail=error_body("VALIDATION_ERROR", "A messages array is required"))
    messages = []
    if len(incoming["messages"]) > 24:
        raise HTTPException(status_code=422, detail=error_body("VALIDATION_ERROR", "Too many conversation messages"))
    allowed_roles = {"system", "user", "assistant", "tool"}
    for item in incoming["messages"]:
        if not isinstance(item, dict) or item.get("role") not in allowed_roles:
            raise HTTPException(status_code=422, detail=error_body("VALIDATION_ERROR", "Invalid message role"))
        content = item.get("content", "")
        if content is None and item["role"] == "assistant" and isinstance(item.get("tool_calls"), list):
            content = ""
        if not isinstance(content, str) or len(content) > 12000:
            raise HTTPException(status_code=422, detail=error_body("VALIDATION_ERROR", "Message content must be text under 12,000 characters"))
        message = {"role": item["role"], "content": content}
        if item["role"] == "tool" and isinstance(item.get("tool_call_id"), str):
            message["tool_call_id"] = item["tool_call_id"][:128]
        if item["role"] == "assistant" and isinstance(item.get("tool_calls"), list):
            safe_calls = []
            for call in item["tool_calls"][:8]:
                if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                    continue
                fn = call["function"]
                if isinstance(fn.get("name"), str) and isinstance(fn.get("arguments"), str):
                    safe_calls.append({"id": str(call.get("id", ""))[:128], "type": "function", "function": {"name": fn["name"][:64], "arguments": fn["arguments"][:12000]}})
            if safe_calls:
                message["tool_calls"] = safe_calls
        messages.append(message)
    if not messages:
        raise HTTPException(status_code=422, detail=error_body("VALIDATION_ERROR", "At least one message is required"))

    payload: dict = {"model": settings.llm_model, "messages": messages, "temperature": 0.1, "max_completion_tokens": 1200, "stream": False}
    tools = incoming.get("tools")
    if isinstance(tools, list) and tools:
        safe_tools = []
        for item in tools[:8]:
            if not isinstance(item, dict) or item.get("type") != "function" or not isinstance(item.get("function"), dict):
                continue
            fn = item["function"]
            name, description, parameters = fn.get("name"), fn.get("description", ""), fn.get("parameters")
            if not isinstance(name, str) or not name.replace("_", "").isalnum() or not isinstance(parameters, dict):
                continue
            safe_tools.append({"type": "function", "function": {"name": name[:64], "description": str(description)[:500], "parameters": parameters}})
        if safe_tools:
            payload["tools"] = safe_tools
            choice = incoming.get("tool_choice", "auto")
            if choice in ("auto", "none", "required"):
                payload["tool_choice"] = choice
            elif isinstance(choice, dict) and isinstance(choice.get("function"), dict) and isinstance(choice["function"].get("name"), str):
                payload["tool_choice"] = {"type": "function", "function": {"name": choice["function"]["name"][:64]}}
            else:
                payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = False
    if isinstance(incoming.get("response_format"), dict) and incoming["response_format"].get("type") == "json_object":
        payload["response_format"] = {"type": "json_object"}
    now = time.monotonic()
    while ai_requests and now - ai_requests[0] > 60:
        ai_requests.popleft()
    if len(ai_requests) >= 20:
        raise HTTPException(status_code=429, detail=error_body("UPSTREAM_ERROR", "AI rate limit exceeded", {"limit": 20, "window_seconds": 60}))
    ai_requests.append(now)
    import httpx
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_s) as client:
            response = await client.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"}, json=payload)
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail=error_body("UPSTREAM_ERROR", "Groq rejected the analyst request", {"status": response.status_code, "upstream": response.text[:500]}))
        return JSONResponse(content=response.json())
    except httpx.TimeoutException as error:
        raise HTTPException(status_code=504, detail=error_body("UPSTREAM_ERROR", "Groq request timed out")) from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail=error_body("UPSTREAM_ERROR", "Could not reach Groq")) from error


@app.get("/paypal/config", dependencies=[Depends(require_token)])
def paypal_checkout_config() -> dict:
    return {"mode": settings.paypal_mode, "client_id": settings.paypal_client_id if settings.paypal_mode == "sandbox" else None, "currency": "USD"}


@app.post("/paypal/orders", dependencies=[Depends(require_token)])
async def create_paypal_order(body: PayPalOrderBody) -> dict:
    if settings.paypal_mode != "sandbox":
        raise HTTPException(status_code=409, detail=error_body("SANDBOX_REQUIRED", "PayPal Checkout is available only when PAYPAL_MODE=sandbox"))
    try:
        result = await get_adapter().create_order(Decimal(str(body.amount)).quantize(Decimal("0.01")), body.currency)
        return {"id": result.get("id"), "status": result.get("status"), "links": result.get("links", [])}
    except Exception as error:
        raise HTTPException(status_code=502, detail=error_body("PAYPAL_ERROR", "PayPal sandbox could not create the order", {"reason": str(error)[:300]})) from error


@app.post("/paypal/orders/{order_id}/capture", dependencies=[Depends(require_token)])
async def capture_paypal_order(order_id: str) -> dict:
    if settings.paypal_mode != "sandbox":
        raise HTTPException(status_code=409, detail=error_body("SANDBOX_REQUIRED", "PayPal Checkout is available only when PAYPAL_MODE=sandbox"))
    if not order_id or len(order_id) > 80 or not order_id.replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail=error_body("VALIDATION_ERROR", "Invalid PayPal order ID"))
    try:
        return await get_adapter().capture_order(order_id)
    except Exception as error:
        raise HTTPException(status_code=502, detail=error_body("PAYPAL_ERROR", "PayPal sandbox could not capture this order", {"reason": str(error)[:300]})) from error


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

        # Never expose a simulated order through a real dispute, or vice versa.
        if order and order.simulated != dispute.simulated:
            order = None

        assessment = db.scalar(
            select(Assessment).where(Assessment.dispute_id == dispute.id)
        )
        decision = db.scalar(
            select(Decision).where(Decision.dispute_id == dispute.id)
        )

        deadline = (
            dispute.deadline.replace(tzinfo=timezone.utc)
            if dispute.deadline and dispute.deadline.tzinfo is None
            else dispute.deadline
        )

        hours = (
            (deadline - datetime.now(timezone.utc)).total_seconds() / 3600
            if deadline is not None
            else None
        )

        created = dispute.created_at.date().isoformat()

        rows.append({
            "id": dispute.id,
            "paypal_dispute_id": dispute.paypal_dispute_id,
            "customer_name": order.customer_name if order else "Unknown customer",
            "amount_value": float(dispute.amount),
            "currency": dispute.currency,
            "reason": dispute.reason,
            "status": dispute.status,
            "decision": decision.policy_decision if decision else None,
            "final_action": decision.final_action if decision else None,
            "win_likelihood": assessment.win_likelihood if assessment else 0,
            "confidence": assessment.confidence if assessment else 0,
            "checklist_score": assessment.checklist_score if assessment else 0,
            "rationale": assessment.rationale if assessment else None,
            "llm_error": assessment.llm_error if assessment else None,
            "has_conflict": bool(assessment and assessment.conflicts_json),
            "conflict_summary": (
                assessment.conflicts_json[0]
                if assessment and assessment.conflicts_json
                else None
            ),
            "guardrail_rule": decision.guardrail_rule if decision else None,
            "simulated": dispute.simulated,
            "created_at": dispute.created_at,
            "deadline": deadline,
            "hours_to_deadline": round(hours, 2) if hours is not None else None,
            "resolved_at": dispute.resolved_at,
            "day": created,
            "week": (
                f"{dispute.created_at.isocalendar().year}"
                f"-W{dispute.created_at.isocalendar().week:02d}"
            ),
        })

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
    rows = db.execute(select(Decision, Dispute).join(Dispute, Dispute.id == Decision.dispute_id).where(Decision.guardrail_rule.is_not(None))).all()
    return [{"dispute_id": decision.dispute_id, "rule": decision.guardrail_rule, "outcome": "downgraded_to_escalate", "simulated": dispute.simulated} for decision, dispute in rows]


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
