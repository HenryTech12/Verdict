"""End-to-end acceptance tests for the PRD demo cases, run through the real webhook path."""
import json
import time
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.adapters.paypal_mock import SIGNATURE_HEADER, sign_payload
from app.db import SessionLocal
from app.llm.base import AssessmentOutput
from app.models import Action, AuditLog, Dispute
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
    resolved = {**created, "id": "WH-RESOLVED", "event_type": "CUSTOMER.DISPUTE.RESOLVED", "resource": {**created["resource"], "dispute_outcome": {"outcome_code": "RESOLVED_SELLER_FAVOUR"}}}
    assert signed_post(client, resolved).status_code == 200
    assert client.get(f"/disputes/{dispute_id}").json()["status"] == "RESOLVED"


def test_unknown_order_escalates_for_missing_evidence(client):
    payload = {"id": "WH-REAL-1", "event_type": "CUSTOMER.DISPUTE.CREATED", "resource": {"dispute_id": "PP-D-9999", "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "dispute_amount": {"value": "60.00", "currency_code": "USD"}, "disputed_transactions": [{"seller_transaction_id": "NOT-IN-OUR-DB"}]}}
    assert signed_post(client, payload).status_code == 200
    detail = client.get("/disputes").json()["items"][0]
    assert detail["status"] == "AWAITING_APPROVAL" and detail["guardrail_rule"] == "MISSING_EVIDENCE"
    assert detail["simulated"] is False


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
