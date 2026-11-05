"""Dispute simulator (F2): seeds matching store data, then fires a signed PayPal-style webhook at
our own /webhooks/paypal endpoint, so the simulated flow exercises the same path as a real event."""
import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.paypal_mock import SIGNATURE_HEADER, sign_payload
from app.models import Dispute, Message, Order, Shipment
from app.services.merchant import get_merchant
from app.services.scenarios import PAYPAL_REASONS, SCENARIOS


def seed_store_data(db: Session, case: str) -> tuple[Order, str]:
    s = SCENARIOS[case]
    now = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex[:8].upper()
    order = Order(id=f"ORD-{suffix}", merchant_id=get_merchant(db).id, customer_name=s.customer, amount=s.amount, currency="USD", items_json=[{"name": s.item, "qty": 1, "matches_listing": s.matches_listing, "pack_photo": s.pack_photo}], ship_address=s.ship_address, policy_accepted=s.policy_accepted, paypal_capture_id=f"SIM-CAP-{suffix}")
    db.add(order)
    db.flush()
    db.add(Shipment(order_id=order.id, carrier="SIMULATED CARRIER", tracking=f"SIM-TRK-{suffix}", status="DELIVERED", delivered_at=now - timedelta(days=3), delivery_address=s.delivery_address, proof_url="SIMULATED delivery-photo.jpg" if s.proof else None))
    db.add_all([Message(order_id=order.id, sender="customer", text=s.customer_message, ts=now - timedelta(days=2)), Message(order_id=order.id, sender="merchant", text=s.merchant_message, ts=now - timedelta(days=2, hours=-1))])
    db.commit()
    return order, f"SIM-PP-{suffix}"


def build_payload(case: str, order: Order, paypal_dispute_id: str) -> dict:
    s = SCENARIOS[case]
    due = datetime.now(timezone.utc) + timedelta(hours=s.deadline_hours)
    return {
        "id": f"WH-{uuid.uuid4().hex[:12].upper()}",
        "event_type": "CUSTOMER.DISPUTE.CREATED",
        "create_time": datetime.now(timezone.utc).isoformat(),
        "verdict_simulated": True,
        "verdict_case": case,
        "resource": {
            "dispute_id": paypal_dispute_id,
            "reason": PAYPAL_REASONS[s.reason],
            "status": "WAITING_FOR_SELLER_RESPONSE",
            "dispute_amount": {"currency_code": "USD", "value": str(s.amount)},
            "seller_response_due_date": due.isoformat(),
            "disputed_transactions": [{"seller_transaction_id": order.paypal_capture_id, "buyer": {"name": s.customer}}],
        },
    }


async def fire_simulated_dispute(app, db: Session, case: str, timeout_s: float = 20.0) -> str:
    order, paypal_id = seed_store_data(db, case)
    body = json.dumps(build_payload(case, order, paypal_id)).encode()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://verdict.local") as client:
        response = await client.post("/webhooks/paypal", content=body, headers={"content-type": "application/json", SIGNATURE_HEADER: sign_payload(body)})
    if response.status_code >= 400:
        raise RuntimeError(f"Simulated webhook rejected: {response.status_code} {response.text}")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:  # the webhook acknowledges immediately; wait for the pipeline to settle
        db.expire_all()
        dispute = db.scalar(select(Dispute).where(Dispute.paypal_dispute_id == paypal_id))
        if dispute and dispute.status not in ("NEW", "ASSESSING"):
            return dispute.id
        await asyncio.sleep(0.05)
    raise TimeoutError("Pipeline did not finish within the demo budget")
