"""Webhook ingestion: idempotent by PayPal event id and by dispute id."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Dispute, Order, WebhookEvent, now_utc
from app.services.errors import RuleError
from app.services.events import event_bus
from app.services.gather import normalize_reason
from app.services.merchant import get_merchant
from app.services.pipeline import announce, log
from app.services.serializers import serialize_dispute

SUPPORTED = {"CUSTOMER.DISPUTE.CREATED", "CUSTOMER.DISPUTE.UPDATED", "CUSTOMER.DISPUTE.RESOLVED"}

def _parse_due(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _amount(resource: dict[str, Any], fallback: Decimal | None) -> tuple[Decimal, str]:
    block = resource.get("dispute_amount") or {}
    try:
        return Decimal(str(block["value"])), str(block.get("currency_code", "USD"))
    except (KeyError, InvalidOperation):
        return fallback or Decimal("0"), "USD"


async def ingest(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    event_id, event_type = payload.get("id"), payload.get("event_type", "")
    resource = payload.get("resource") or {}
    if not event_id or not resource.get("dispute_id"):
        raise RuleError("INVALID_WEBHOOK", "Webhook needs an event id and resource.dispute_id", 422)
    db.add(WebhookEvent(event_id=event_id, event_type=event_type))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate", "event_id": event_id}
    if event_type not in SUPPORTED:
        return {"status": "ignored", "event_id": event_id}

    paypal_id = resource["dispute_id"]
    dispute = db.scalar(select(Dispute).where(Dispute.paypal_dispute_id == paypal_id))
    if dispute:
        if event_type.endswith("RESOLVED"):
            dispute.paypal_status = (
                resource.get("status") or "RESOLVED"
            )
            dispute.resolved_at = now_utc()
            db.commit()

            log(
                db,
                dispute,
                "INGEST",
                "PayPal reported the dispute resolved",
                input_json={
                    "event_type": event_type,
                    "status": dispute.paypal_status,
                    "outcome": resource.get("dispute_outcome"),
                },
            )
            announce(db, dispute, ["status", "paypal_status"])

        elif event_type.endswith("UPDATED"):
            dispute.paypal_status = (
                resource.get("status") or dispute.paypal_status
            )
            db.commit()

            log(
                db,
                dispute,
                "INGEST",
                "PayPal dispute update received",
                input_json={
                    "event_type": event_type,
                    "status": dispute.paypal_status,
                },
            )
            announce(db, dispute, ["paypal_status"])

        return {
            "status": "updated",
            "event_id": event_id,
            "dispute_id": dispute.id,
            "run": False,
        }

    txn = (resource.get("disputed_transactions") or [{}])[0]
    capture_id = str(txn.get("seller_transaction_id") or "")
    is_simulated = bool(payload.get("verdict_simulated"))

    order = (
        db.scalar(
            select(Order).where(
                Order.paypal_capture_id == capture_id,
                Order.simulated.is_(is_simulated),
            )
        )
        if capture_id else None
    )    
    amount, currency = _amount(resource, order.amount if order else None)
    if not order:  # no local record for this capture: evidence gathering will report it as missing
        order = Order(id=f"ORD-{uuid.uuid4().hex[:8].upper()}", merchant_id=get_merchant(db).id, customer_name=(txn.get("buyer") or {}).get("name") or "Unknown customer", amount=amount, currency=currency, items_json=[], ship_address="Unknown", policy_accepted=False, paypal_capture_id=capture_id or "UNKNOWN",simulated=is_simulated)
        db.add(order)
        db.flush()
    dispute = Dispute(id=f"DSP-{uuid.uuid4().hex[:6].upper()}", paypal_dispute_id=paypal_id, order_id=order.id, reason=normalize_reason(str(resource.get("reason", ""))), amount=amount, currency=currency, status="NEW", deadline=_parse_due(resource.get("seller_response_due_date")), simulated=is_simulated, case=str(payload.get("verdict_case", "R"))[:1])
    db.add(dispute)
    db.commit()
    log(db, dispute, "INGEST", "Webhook verified and dispute created", input_json={"event_id": event_id, "event_type": event_type, "paypal_dispute_id": paypal_id})
    event_bus.publish("dispute_created", {"dispute": _json(serialize_dispute(db, dispute))})
    return {"status": "created", "event_id": event_id, "dispute_id": dispute.id, "run": True}


def _json(value: Any) -> Any:
    import json

    return json.loads(json.dumps(value, default=str))
