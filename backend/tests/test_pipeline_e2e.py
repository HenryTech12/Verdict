"""End-to-end acceptance tests for the PRD demo cases, run through the real webhook path."""
import json
import time
from decimal import Decimal
from xmlrpc import client

import pytest
from sqlalchemy import func, select

from app.adapters.paypal_mock import SIGNATURE_HEADER, sign_payload
from app.db import SessionLocal
from app.llm.base import AssessmentOutput
from app.models import Action, AuditLog, Dispute, Message, Order, Shipment
from app import main
from app.config import settings
from app.services import pipeline
from app.services.scenarios import SCENARIOS
from app.services.simulator import build_payload, seed_store_data
from tests.conftest import run_case


def steps(detail: dict) -> list[str]:
    return [entry["step"] for entry in detail["audit"]]


def action_count(dispute_id: str) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(Action).where(Action.dispute_id == dispute_id))


@pytest.mark.parametrize("run", [1, 2, 3])  # PRD: cases A, B and C pass three consecutive runs
def test_cases_a_b_c_acceptance(client, run):
    started = time.perf_counter()
    a, b, c = (run_case(client, case) for case in "ABC")
    assert time.perf_counter() - started < 20

    # A: easy fight, evidence packet submitted automatically
    assert a["status"] == "EVIDENCE_SUBMITTED" and a["decision"]["final_action"] == "FIGHT"
    assert a["assessment"]["win_likelihood"] >= 0.6 and not a["assessment"]["conflicts"]
    assert "Seller response" in a["assessment"]["packet_draft"]
    assert steps(a) == ["INGEST", "GATHER", "ASSESS", "DECIDE", "GUARD", "ACT", "LOG"]

    # B: conflict detected, agent chooses not to fight and refunds under the cap
    assert b["status"] == "REFUNDED" and b["decision"]["final_action"] == "REFUND"
    assert b["assessment"]["conflicts"] and b["assessment"]["win_likelihood"] <= 0.25
    assert "does not match" in b["assessment"]["conflicts"][0]
    assert b["shipment"]["delivery_address"] != b["order"]["ship_address"]

    # C: strong evidence, but the guardrail forces approval
    assert c["status"] == "AWAITING_APPROVAL"
    assert c["decision"]["policy_decision"] == "FIGHT" and c["decision"]["final_action"] == "ESCALATE"
    assert c["guardrail_rule"] == "AMOUNT_ABOVE_APPROVAL_THRESHOLD"
    assert c["approval"]["requested_action"] == "FIGHT" and action_count(c["id"]) == 0  # nothing executed yet

    approved = client.post(f"/disputes/{c['id']}/approve", json={"note": "Looks right"})
    assert approved.status_code == 200 and approved.json()["status"] == "EVIDENCE_SUBMITTED"
    assert approved.json()["approval"]["status"] == "APPROVED" and approved.json()["approval"]["note"] == "Looks right"
    assert action_count(c["id"]) == 1


def test_every_step_is_audited_with_inputs_outputs_and_rule(client):
    detail = run_case(client, "B")
    by_step = {entry["step"]: entry for entry in detail["audit"]}
    assert by_step["GATHER"]["output"]["tool_calls"] and by_step["ASSESS"]["input"]["context"]["shipment"]
    assert by_step["DECIDE"]["output"]["rule_fired"] == "REFUND_THRESHOLD"
    assert by_step["ACT"]["output"]["simulated"] is True
    assert all(entry["ts"] for entry in detail["audit"])


def test_second_reason_code_case_d(client):
    d = run_case(client, "D")
    assert d["reason"] == "NOT_AS_DESCRIBED" and d["status"] == "EVIDENCE_SUBMITTED"
    assert any(i["type"] == "ITEM_MATCHES_LISTING" for i in d["assessment"]["evidence_items"])


def test_urgent_case_is_flagged_and_surfaced(client):
    e = run_case(client, "E")
    assert e["status"] == "AWAITING_APPROVAL" and e["urgent"] is True
    assert e["approval"]["status"] == "PENDING"
    assert client.get("/approvals").json()[0]["recommendation_summary"].startswith("URGENT")


def test_expired_deadline_takes_no_action(client):
    f = run_case(client, "F")
    assert f["status"] == "EXPIRED" and f["guardrail_rule"] == "DEADLINE_EXPIRED"
    assert action_count(f["id"]) == 0 and f["approval"] is None


def test_approval_is_idempotent_and_cannot_double_execute(client):
    c = run_case(client, "C")
    assert client.post(f"/disputes/{c['id']}/approve").status_code == 200
    second = client.post(f"/disputes/{c['id']}/approve")
    assert second.status_code == 409 and second.json()["error"]["code"] == "ALREADY_PROCESSED"
    assert client.post(f"/disputes/{c['id']}/reject").status_code == 409
    assert action_count(c["id"]) == 1


def test_reject_closes_without_action(client):
    c = run_case(client, "C")
    rejected = client.post(f"/disputes/{c['id']}/reject", json={"note": "I'll handle it"})
    assert rejected.status_code == 200 and rejected.json()["status"] == "RESOLVED"
    assert action_count(c["id"]) == 0


def test_perform_action_claims_its_idempotency_key():
    import asyncio

    async def twice():
        with SessionLocal() as db:
            dispute = db.scalar(select(Dispute))
            first = await pipeline.perform_action(db, dispute, "REFUND", "")
            second = await pipeline.perform_action(db, dispute, "REFUND", "")
            return first, second

    from app.db import Base, engine

    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with SessionLocal() as db:
        from app.services.simulator import seed_store_data as seed_data
        from app.services.ingest import ingest

        order, paypal_id = seed_data(db, "B")
        payload = build_payload("B", order, paypal_id)
        asyncio.run(ingest(db, payload))
    first, second = asyncio.run(twice())
    assert "already_executed" not in first and second["already_executed"] is True
    assert action_count(first_id()) == 1


def first_id() -> str:
    with SessionLocal() as db:
        return db.scalar(select(Dispute.id))


def signed_post(client, payload: dict, signature: str | None = "valid"):
    body = json.dumps(payload).encode()
    headers = {"content-type": "application/json"}
    if signature == "valid":
        headers[SIGNATURE_HEADER] = sign_payload(body)
    elif signature:
        headers[SIGNATURE_HEADER] = signature
    return client.post("/webhooks/paypal", content=body, headers=headers)


def test_webhook_rejects_missing_or_bad_signatures(client):
    with SessionLocal() as db:
        order, paypal_id = seed_store_data(db, "A")
    payload = build_payload("A", order, paypal_id)
    assert signed_post(client, payload, None).status_code == 401
    assert signed_post(client, payload, "deadbeef").status_code == 401
    assert client.get("/disputes").json()["total"] == 0


def test_webhook_is_idempotent_by_event_and_dispute_id(client):
    with SessionLocal() as db:
        order, paypal_id = seed_store_data(db, "A")
    payload = build_payload("A", order, paypal_id)
    assert signed_post(client, payload).json()["status"] == "created"
    assert signed_post(client, payload).json()["status"] == "duplicate"  # same event id
    again = {**payload, "id": "WH-ANOTHER"}  # new event, same dispute
    assert signed_post(client, again).json()["status"] == "updated"
    assert client.get("/disputes").json()["total"] == 1
    assert action_count(client.get("/disputes").json()["items"][0]["id"]) == 1


def test_webhook_updated_and_resolved_events(client):
    with SessionLocal() as db:
        order, paypal_id = seed_store_data(db, "C")

    created = build_payload("C", order, paypal_id)
    dispute_id = signed_post(client, created).json()["dispute_id"]

    # First, verify an ordinary PayPal update does not overwrite
    # Verdict's internal workflow status.
    updated = {
        **created,
        "id": "WH-UPDATED",
        "event_type": "CUSTOMER.DISPUTE.UPDATED",
        "resource": {
            **created["resource"],
            "status": "WAITING_FOR_BUYER_RESPONSE",
        },
    }

    assert signed_post(client, updated).status_code == 200

    with SessionLocal() as db:
        dispute = db.get(Dispute, dispute_id)
        assert dispute.paypal_status == "WAITING_FOR_BUYER_RESPONSE"

    # Then verify a resolved event updates PayPal's status
    # without overwriting Verdict's internal status.
    resolved = {
        **created,
        "id": "WH-RESOLVED",
        "event_type": "CUSTOMER.DISPUTE.RESOLVED",
        "resource": {
            **created["resource"],
            "status": "RESOLVED",
            "dispute_outcome": {
                "outcome_code": "RESOLVED_SELLER_FAVOUR"
            },
        },
    }

    assert signed_post(client, resolved).status_code == 200

    with SessionLocal() as db:
        dispute = db.get(Dispute, dispute_id)
        assert dispute.status == "AWAITING_APPROVAL"
        assert dispute.paypal_status == "RESOLVED"
        assert dispute.resolved_at is not None

def test_unknown_order_escalates_for_missing_evidence(client):
    payload = {"id": "WH-REAL-1", "event_type": "CUSTOMER.DISPUTE.CREATED", "resource": {"dispute_id": "PP-D-9999", "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "dispute_amount": {"value": "60.00", "currency_code": "USD"}, "disputed_transactions": [{"seller_transaction_id": "NOT-IN-OUR-DB"}]}}
    assert signed_post(client, payload).status_code == 200
    detail = client.get("/disputes").json()["items"][0]
    assert detail["status"] == "AWAITING_APPROVAL" and detail["guardrail_rule"] == "MISSING_EVIDENCE"
    assert detail["simulated"] is False

def test_missing_evidence_blocks_fight_approval_but_allows_refund(client):
    payload = {
        "id": "WH-REAL-APPROVAL-1",
        "event_type": "CUSTOMER.DISPUTE.CREATED",
        "resource": {
            "dispute_id": "PP-D-APPROVAL-1",
            "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
            "dispute_amount": {
                "value": "60.00",
                "currency_code": "USD",
            },
            "disputed_transactions": [
                {"seller_transaction_id": "UNKNOWN-CAPTURE-APPROVAL"}
            ],
        },
    }

    response = signed_post(client, payload)
    assert response.status_code == 200

    dispute = client.get("/disputes").json()["items"][0]
    dispute_id = dispute["id"]

    detail = client.get(f"/disputes/{dispute_id}").json()

    assert detail["status"] == "AWAITING_APPROVAL"
    assert detail["approval"]["requested_action"] == "REFUND"

    # A merchant must not override the refund recommendation with FIGHT.
    blocked = client.post(
        f"/disputes/{dispute_id}/approve",
        json={"action": "FIGHT"},
    )

    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "GUARDRAIL_BLOCKED"
    assert action_count(dispute_id) == 0

    # The rejected override must leave the approval pending.
    pending = client.get(f"/disputes/{dispute_id}").json()
    assert pending["approval"]["status"] == "PENDING"

    # A refund is still permitted with merchant approval.
    refunded = client.post(
        f"/disputes/{dispute_id}/approve",
        json={"action": "REFUND"},
    )

    assert refunded.status_code == 200, refunded.text
    assert refunded.json()["status"] == "REFUNDED"
    assert refunded.json()["approval"]["status"] == "APPROVED"
    assert action_count(dispute_id) == 1

def test_model_failure_escalates_with_error_logged(client, monkeypatch):
    class Broken:
        async def assess(self, _context):
            raise RuntimeError("model unavailable after 3 attempts")

    monkeypatch.setattr(pipeline, "provider", lambda: Broken())
    a = run_case(client, "A")
    assert a["status"] == "AWAITING_APPROVAL" and a["guardrail_rule"] == "LOW_CONFIDENCE"
    assert "model unavailable" in a["assessment"]["llm_error"]


def test_model_cannot_override_guardrails(client, monkeypatch):
    class Overconfident:
        async def assess(self, _context):
            return AssessmentOutput(evidence_items=[], conflicts=[], win_likelihood=1.0, confidence=1.0, recommended="FIGHT", rationale="Trust me, fight everything.", packet_draft="x")

    monkeypatch.setattr(pipeline, "provider", lambda: Overconfident())
    b = run_case(client, "B")  # conflicting address evidence: the checklist still caps the win likelihood
    assert b["assessment"]["win_likelihood"] <= 0.25 and b["status"] == "REFUNDED"
    c = run_case(client, "C")
    assert c["status"] == "AWAITING_APPROVAL"  # $480 needs a human no matter what the model says


def test_qualitative_conflict_from_messages_blocks_auto_fight(client, monkeypatch):
    from app.models import Message

    monkeypatch.setattr(pipeline, "provider", pipeline.provider)
    with SessionLocal() as db:
        order, paypal_id = seed_store_data(db, "A")
        db.add(Message(order_id=order.id, sender="customer", text="It was left with a neighbour at the wrong address."))
        db.commit()
    assert signed_post(client, build_payload("A", order, paypal_id)).status_code == 200
    item = client.get("/disputes").json()["items"][0]
    assert item["status"] == "AWAITING_APPROVAL" and item["guardrail_rule"] == "CONFLICTING_EVIDENCE"


def test_merchant_settings_are_applied_per_merchant_and_persist(client):
    current = client.get("/settings").json()
    updated = client.put("/settings", json={**current, "auto_refund_cap": "50.00"})
    assert updated.status_code == 200
    b = run_case(client, "B")  # $90 refund is now above the $50 cap
    assert b["status"] == "AWAITING_APPROVAL" and b["guardrail_rule"] == "REFUND_ABOVE_AUTO_REFUND_CAP"
    assert client.put("/settings", json={**current, "fight_min_win_likelihood": 0.2, "refund_max_win_likelihood": 0.3}).status_code == 422


def test_packet_download_and_metrics(client):
    a = run_case(client, "A")
    run_case(client, "B")
    packet = client.get(f"/disputes/{a['id']}/packet")
    assert packet.status_code == 200 and "attachment" in packet.headers["content-disposition"] and "Tracking number" in packet.text
    metrics = client.get("/metrics").json()
    assert metrics["disputes_handled"] == 2 and Decimal(metrics["modeled_revenue_recovered"]) > 0
    assert metrics["assumptions"]["label"].startswith("MODELED")


def test_list_filters_and_auth(client):
    run_case(client, "A"); run_case(client, "C")
    assert client.get("/disputes?status=AWAITING_APPROVAL").json()["total"] == 1
    assert client.get("/disputes?search=Mina").json()["total"] == 1
    assert client.get("/disputes", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/disputes/DSP-NOPE").status_code == 404
    assert client.post("/sim/dispute?case=Z").status_code == 422


def test_simulator_webhooks_still_work_in_sandbox_mode(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "paypal_mode", "sandbox")  # adapter now expects real PayPal signatures
    monkeypatch.setattr(settings, "paypal_client_id", "x")
    monkeypatch.setattr(settings, "paypal_client_secret", "y")
    with SessionLocal() as db:
        order, paypal_id = seed_store_data(db, "A")
    payload = build_payload("A", order, paypal_id)
    assert signed_post(client, payload, "deadbeef").status_code == 401  # a bad signature never passes via either path
    assert signed_post(client, payload).json()["status"] == "created"  # a valid simulator HMAC does


class FakeCapturePayPal:
    simulated = False

    def __init__(self, capture=None, order=None):
        self.capture = capture or {
            "id": "REALCAPTURE123",
            "status": "COMPLETED",
            "amount": {
                "value": "90.00",
                "currency_code": "USD",
            },
        }

        self.order = order or {
            "id": "PAYPAL-ORDER-123",
            "status": "COMPLETED",
            "purchase_units": [
                {
                    "payments": {
                        "captures": [
                            {
                                "id": "REALCAPTURE123",
                                "status": "COMPLETED",
                                "amount": {
                                    "value": "90.00",
                                    "currency_code": "USD",
                                },
                            }
                        ]
                    }
                }
            ],
        }

    async def get_capture(self, capture_id):
        return self.capture

    async def get_order(self, order_id):
        return self.order
    
def test_real_capture_registration_uses_only_verified_payment_data(client, monkeypatch):
    monkeypatch.setattr(settings, "paypal_mode", "sandbox")
    monkeypatch.setattr(
        main, "get_adapter",
        lambda: FakeCapturePayPal(),
    )

    response = client.post(
        "/orders/register-capture",
        params={
            "capture_id": "REALCAPTURE123",
            "paypal_order_id": "PAYPAL-ORDER-123",
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()

    assert data["capture_id"] == "REALCAPTURE123"
    assert data["amount"] == "90.00"
    assert data["currency"] == "USD"
    assert data["simulated"] is False

    with SessionLocal() as db:
        order = db.get(Order, data["order_id"])
        assert order is not None
        assert order.customer_name == "Unknown customer"
        assert order.amount == Decimal("90.00")
        assert order.currency == "USD"
        assert order.items_json == []
        assert order.ship_address == "Not provided"
        assert order.policy_accepted is False

        assert db.get(Shipment, order.id) is None
        assert db.scalar(
            select(func.count()).select_from(Message).where(
                Message.order_id == order.id
            )
        ) == 0

    duplicate = client.post(
        "/orders/register-capture",
        params={
            "capture_id": "REALCAPTURE123",
            "paypal_order_id": "PAYPAL-ORDER-123",
        },
    )
    assert duplicate.status_code == 409


def test_real_capture_registration_rejects_uncompleted_capture(client, monkeypatch):
    monkeypatch.setattr(settings, "paypal_mode", "sandbox")
    monkeypatch.setattr(
        main, "get_adapter",
        lambda: FakeCapturePayPal({
            "id": "REALCAPTURE123",
            "status": "PENDING",
            "amount": {
                "value": "90.00",
                "currency_code": "USD",
            },
        }),
    )

    response = client.post(
        "/orders/register-capture",
        params={
            "capture_id": "REALCAPTURE123",
            "paypal_order_id": "PAYPAL-ORDER-123",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CAPTURE_NOT_COMPLETED"


def test_real_capture_registration_rejects_wrong_paypal_order(client, monkeypatch):
    monkeypatch.setattr(settings, "paypal_mode", "sandbox")
    monkeypatch.setattr(
        main, "get_adapter",
        lambda: FakeCapturePayPal(),
    )

    response = client.post(
        "/orders/register-capture",
        params={
            "capture_id": "REALCAPTURE123",
            "paypal_order_id": "ANOTHER-ORDER",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PAYPAL_ORDER_MISMATCH"


def test_real_capture_registration_rejects_mock_mode(client):
    response = client.post(
        "/orders/register-capture",
        params={
            "capture_id": "REALCAPTURE123",
            "paypal_order_id": "PAYPAL-ORDER-123",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PAYPAL_MODE_REQUIRED"

def test_real_capture_registration_rejects_order_without_capture(
    client, monkeypatch
):
    monkeypatch.setattr(settings, "paypal_mode", "sandbox")

    fake = FakeCapturePayPal(
        order={
            "id": "PAYPAL-ORDER-123",
            "status": "COMPLETED",
            "purchase_units": [],
        }
    )

    monkeypatch.setattr(main, "get_adapter", lambda: fake)

    response = client.post(
        "/orders/register-capture",
        params={
            "capture_id": "REALCAPTURE123",
            "paypal_order_id": "PAYPAL-ORDER-123",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PAYPAL_ORDER_MISMATCH"


def test_perform_action_blocks_fight_when_evidence_is_missing(client):
    import asyncio
    from app.services.errors import RuleError

    payload = {
        "id": "WH-DIRECT-GUARD-1",
        "event_type": "CUSTOMER.DISPUTE.CREATED",
        "resource": {
            "dispute_id": "PP-D-DIRECT-GUARD-1",
            "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
            "dispute_amount": {
                "value": "60.00",
                "currency_code": "USD",
            },
            "disputed_transactions": [
                {"seller_transaction_id": "UNKNOWN-CAPTURE-DIRECT"}
            ],
        },
    }

    response = signed_post(client, payload)
    assert response.status_code == 200

    with SessionLocal() as db:
        dispute = db.scalar(
            select(Dispute).where(
                Dispute.paypal_dispute_id == "PP-D-DIRECT-GUARD-1"
            )
        )

        assert dispute is not None
        dispute_id = dispute.id

        with pytest.raises(RuleError) as error:
            asyncio.run(
                pipeline.perform_action(db, dispute, "FIGHT", "")
            )

        assert error.value.code == "GUARDRAIL_BLOCKED"

    # The blocked operation must not create an Action record.
    assert action_count(dispute_id) == 0



def test_real_dispute_does_not_expose_linked_simulated_order_or_shipment(client):
    # Create a simulated order with synthetic customer and shipping data.
    with SessionLocal() as db:
        simulated_order, _ = seed_store_data(db, "A")
        simulated_order_id = simulated_order.id

    # Create a real dispute using an unrelated, unknown PayPal capture ID.
    payload = {
        "id": "WH-SERIALIZER-LEAK-1",
        "event_type": "CUSTOMER.DISPUTE.CREATED",
        "resource": {
            "dispute_id": "PP-D-SERIALIZER-LEAK-1",
            "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
            "dispute_amount": {
                "value": "60.00",
                "currency_code": "USD",
            },
            "disputed_transactions": [
                {
                    "seller_transaction_id": "UNKNOWN-CAPTURE-SERIALIZER"
                }
            ],
        },
    }

    response = signed_post(client, payload)
    assert response.status_code == 200

    # Deliberately create the bad link: real dispute -> simulated order.
    with SessionLocal() as db:
        dispute = db.scalar(
            select(Dispute).where(
                Dispute.paypal_dispute_id == "PP-D-SERIALIZER-LEAK-1"
            )
        )
        assert dispute is not None

        dispute.order_id = simulated_order_id
        db.commit()
        dispute_id = dispute.id

    # The detail endpoint must hide the incompatible order and shipment.
    detail_response = client.get(f"/disputes/{dispute_id}")
    assert detail_response.status_code == 200

    detail = detail_response.json()
    assert detail["customer_name"] == "Unknown"
    assert detail["order"] is None
    assert detail["shipment"] is None

    # The disputes list must also hide the simulated customer's name.
    list_response = client.get("/disputes")
    assert list_response.status_code == 200

    items = list_response.json()["items"]
    listed_dispute = next(
        item for item in items if item["id"] == dispute_id
    )
    assert listed_dispute["customer_name"] == "Unknown"



def test_perform_action_blocks_fight_when_deadline_is_missing(client):
    import asyncio
    from app.services.errors import RuleError

    # Create a simulated dispute with valid supporting evidence.
    with SessionLocal() as db:
        order, paypal_id = seed_store_data(db, "A")

    payload = build_payload("A", order, paypal_id)
    response = signed_post(client, payload)

    assert response.status_code == 200
    dispute_id = response.json()["dispute_id"]

    with SessionLocal() as db:
        dispute = db.get(Dispute, dispute_id)

        assert dispute is not None

        # Remove the deadline while keeping the supporting evidence.
        dispute.deadline = None
        db.commit()

        # Case A may already have an automatic FIGHT action.
        existing_fight_count = db.scalar(
            select(func.count())
            .select_from(Action)
            .where(
                Action.dispute_id == dispute_id,
                Action.action_type == "FIGHT",
            )
        )

        with pytest.raises(RuleError) as error:
            asyncio.run(
                pipeline.perform_action(db, dispute, "FIGHT", "")
            )

        assert error.value.code == "GUARDRAIL_BLOCKED"
        assert "response deadline" in str(error.value).lower()

    # A blocked FIGHT must not create another FIGHT Action record.
    with SessionLocal() as db:
        final_fight_count = db.scalar(
            select(func.count())
            .select_from(Action)
            .where(
                Action.dispute_id == dispute_id,
                Action.action_type == "FIGHT",
            )
        )

    assert final_fight_count == existing_fight_count
