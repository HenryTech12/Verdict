"""Evidence gathering tools: order record, tracking and delivery status, address match,
customer messages and merchant policy. Everything here reads from the database."""
import re
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dispute, Message, Order, Shipment
from app.services.assessment import REASON_NOT_AS_DESCRIBED, REASON_NOT_RECEIVED, CaseEvidence
from app.services.scenarios import REASON_FROM_PAYPAL


@dataclass
class GatheredCase:
    evidence: CaseEvidence
    context: dict[str, Any]
    missing_evidence: bool
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


def normalize_address(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (value or "").lower())).strip()


def addresses_match(a: str | None, b: str | None) -> bool:
    return bool(normalize_address(a)) and normalize_address(a) == normalize_address(b)


def normalize_reason(reason: str) -> str:
    return REASON_FROM_PAYPAL.get(reason, reason if reason in (REASON_NOT_RECEIVED, REASON_NOT_AS_DESCRIBED) else REASON_NOT_RECEIVED)


def _timed(calls: list[dict[str, Any]], tool: str, fn):
    started = time.perf_counter()
    try:
        value, summary, ok = fn()
    except Exception as error:  # a failing tool lowers confidence instead of aborting the case
        value, summary, ok = None, f"{type(error).__name__}: {error}", False
    calls.append({"tool": tool, "ok": ok, "summary": summary, "duration_ms": round((time.perf_counter() - started) * 1000)})
    return value


def gather(db: Session, dispute: Dispute, policy_text: str) -> GatheredCase:
    calls: list[dict[str, Any]] = []

    order = _timed(
        calls,
        "get_order",
        lambda: (
            lambda o: (
                o,
                f"order {o.id} for {o.customer_name}"
                if o else "no local order record",
                bool(o),
            )
        )(db.get(Order, dispute.order_id)),
    )

    # A real dispute must never use a simulator-generated order.
    compatible_order = bool(
        order and bool(order.simulated) == bool(dispute.simulated)
    )

    # Payment registration alone does not establish customer/order details.
    has_order = bool(
        compatible_order
        and order.ship_address
        and order.ship_address.strip().lower() not in {
            "unknown",
            "not provided",
        }
    )

    # Simulator evidence is only usable for simulator disputes.
    shipment = _timed(
        calls,
        "get_tracking",
        lambda: (
            lambda s: (
                s if has_order else None,
                (
                    f"{s.carrier} {s.tracking}: {s.status}"
                    if s and has_order
                    else "no eligible shipment record found"
                ),
                bool(s and has_order),
            )
        )(db.get(Shipment, dispute.order_id)),
    )

    messages = _timed(
        calls,
        "get_messages",
        lambda: (
            lambda m: (
                m if has_order else [],
                f"{len(m) if has_order else 0} eligible messages",
                bool(has_order),
            )
        )(
            list(
                db.scalars(
                    select(Message)
                    .where(Message.order_id == dispute.order_id)
                    .order_by(Message.ts, Message.id)
                ).all()
            )
        ),
    ) or []

    address_ok = _timed(
        calls,
        "compare_addresses",
        lambda: (
            lambda r: (
                r,
                "order and delivery addresses match"
                if r else "order and delivery addresses differ or are unavailable",
                bool(shipment and has_order),
            )
        )(
            bool(
                shipment
                and has_order
                and addresses_match(
                    order.ship_address,
                    shipment.delivery_address,
                )
            )
        ),
    )

    calls.append({
        "tool": "get_merchant_policy",
        "ok": True,
        "summary": policy_text[:80],
        "duration_ms": 0,
    })

    reason = normalize_reason(dispute.reason)

    merchant_msgs = [m for m in messages if m.sender == "merchant"]
    customer_msgs = [m for m in messages if m.sender == "customer"]

    communication = (
        (0.6 if merchant_msgs else 0.0)
        + (0.4 if customer_msgs else 0.0)
    )

    item = (
        (order.items_json or [{}])[0]
        if has_order and order.items_json
        else {}
    )

    fetch_failures = sum(1 for call in calls if not call["ok"])
    delivered = bool(
        shipment and shipment.status.upper() == "DELIVERED"
    )

    evidence = CaseEvidence(
        delivered=delivered,
        address_match=bool(address_ok),
        proof=bool(shipment and shipment.proof_url),
        communication_strength=communication,
        policy_accepted=bool(has_order and order.policy_accepted),
        fetch_failures=fetch_failures,
        reason=reason,
        matches_listing=bool(item.get("matches_listing", False)),
        pack_photo=bool(item.get("pack_photo", False)),
    )

    context = {
        "dispute": {
            "id": dispute.id,
            "reason": reason,
            "amount": str(dispute.amount),
            "currency": dispute.currency,
        },
        "order": {
            "customer": order.customer_name,
            "ship_address": order.ship_address,
            "items": order.items_json,
            "policy_accepted": order.policy_accepted,
        } if has_order else None,
        "shipment": {
            "carrier": shipment.carrier,
            "tracking": shipment.tracking,
            "status": shipment.status,
            "delivered_at": (
                shipment.delivered_at.strftime("%b %d, %Y")
                if shipment.delivered_at else None
            ),
            "delivery_address": shipment.delivery_address,
            "has_proof": bool(shipment.proof_url),
        } if shipment else None,
        "messages": [
            {"sender": m.sender, "text": m.text[:500]}
            for m in messages
        ][:20],
        "merchant_policy": policy_text,
        "checks": {
            "tracking_delivered": evidence.delivered,
            "address_match": evidence.address_match,
            "delivery_proof": evidence.proof,
            "customer_communication": communication > 0,
            "policy_accepted": evidence.policy_accepted,
            "matches_listing": evidence.matches_listing,
            "pack_photo": evidence.pack_photo,
        },
    }

    return GatheredCase(
        evidence=evidence,
        context=context,
        missing_evidence=not has_order or shipment is None,
        tool_calls=calls,
    )