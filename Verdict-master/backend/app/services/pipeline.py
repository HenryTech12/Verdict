"""Ingest -> Gather -> Assess -> Decide -> Guard -> Act -> Log, per dispute.

Every stage commits an audit entry and publishes a live event. The guardrails engine has final
authority over the model output and can only downgrade an action."""
import asyncio
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters import get_adapter
from app.adapters.paypal_base import UnsupportedInSandbox
from app.adapters.paypal_mock import MockPayPalAdapter
from app.config import settings
from app.db import SessionLocal
from app.llm.base import AssessmentOutput
from app.llm.groq_provider import GroqProvider
from app.llm.mock import MockLLMProvider
from app.models import Action, Approval, Assessment, AuditLog, Decision, Dispute, Message, Order, Shipment
from app.services.assessment import CaseEvidence, assess
from app.services.errors import ActionFailed, RuleError
from app.services.events import event_bus
from app.services.gather import gather
from app.services.guardrails import apply_guardrails, is_expired, is_urgent
from app.services.merchant import settings_for, thresholds
from app.services.packet import build_packet
from app.services.policy import choose_policy_with_rule, lean_action
from app.services.serializers import serialize_dispute

FINAL_STATUS = {"FIGHT": "EVIDENCE_SUBMITTED", "REFUND": "REFUNDED"}


def provider():
    return GroqProvider() if settings.llm_provider == "groq" else MockLLMProvider()


def jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


# ---------------------------------------------------------------- pure decision core (unit-testable)

async def run_assessment(evidence: CaseEvidence, context: dict[str, object]) -> tuple[dict, AssessmentOutput | None, str | None]:
    """LLM assessment plus deterministic scoring. On model failure the checklist stands alone with zero confidence."""
    llm_error: str | None = None
    output: AssessmentOutput | None = None
    try:
        output = await provider().assess(context)
    except Exception as error:  # schema failures and API failures both end in ESCALATE via confidence 0
        llm_error = f"{type(error).__name__}: {error}"[:500]
    if output is None:
        result = assess(evidence, 0.0, 0.0, adjustment_limit=0.0)
    else:
        result = assess(evidence, output.win_likelihood, output.confidence)
        result["conflicts"] = sorted(set(result["conflicts"]) | set(output.conflicts))
    return result, output, llm_error


def decide_and_guard(result: dict, amount: Decimal, deadline_expired: bool, thr: dict[str, object], missing_evidence: bool = False) -> dict:
    recommendation, rule_fired = choose_policy_with_rule(result["win_likelihood"], result["confidence"], float(thr["fight_min_win_likelihood"]), float(thr["refund_max_win_likelihood"]), float(thr["min_confidence"]))
    final_action, guardrail_rule = apply_guardrails(recommendation, amount, deadline_expired, result["confidence"], result["conflicts"], Decimal(str(thr["approval_threshold"])), Decimal(str(thr["auto_refund_cap"])), float(thr["min_confidence"]), missing_evidence)
    return {"recommendation": recommendation, "rule_fired": rule_fired, "final_action": final_action, "guardrail_rule": guardrail_rule}


async def evaluate_case(evidence: CaseEvidence, amount: Decimal, deadline_expired: bool, thresholds_: dict[str, object], context: dict[str, object] | None = None, missing_evidence: bool = False) -> dict:
    context = context or {"checks": {"tracking_delivered": evidence.delivered, "address_match": evidence.address_match, "delivery_proof": evidence.proof, "customer_communication": evidence.communication_strength > 0, "policy_accepted": evidence.policy_accepted}, "dispute": {"reason": evidence.reason}}
    result, output, llm_error = await run_assessment(evidence, context)
    decision = decide_and_guard(result, amount, deadline_expired, thresholds_, missing_evidence)
    result.update({"recommended": decision["recommendation"], "rationale": output.rationale if output else "LLM assessment failed; guardrails require merchant review.", "packet_draft": output.packet_draft if output else "", "llm_error": llm_error, "token_usage": output.token_usage if output else None})
    return {"assessment": result, **decision, "recommendation": decision["recommendation"]}


# ---------------------------------------------------------------- audit + events

def log(db: Session, dispute: Dispute, step: str, summary: str, input_json: Any = None, output_json: Any = None, started: float | None = None) -> None:
    entry = AuditLog(dispute_id=dispute.id, step=step, summary=summary, input_json=jsonable(input_json or {}), output_json=jsonable(output_json or {}), simulated=bool(dispute.simulated or settings.paypal_mode == "mock"), duration_ms=round((time.perf_counter() - started) * 1000) if started else 0)
    db.add(entry)
    db.commit()
    event_bus.publish("audit_added", {"dispute_id": dispute.id, "entry": {"id": entry.id, "step": step, "summary": summary, "simulated": entry.simulated, "duration_ms": entry.duration_ms, "ts": entry.ts.isoformat() if entry.ts else None}})


def announce(db: Session, dispute: Dispute, changed: list[str]) -> None:
    event_bus.publish("dispute_updated", {"dispute": jsonable(serialize_dispute(db, dispute)), "changed": changed})


async def _pause() -> None:
    if settings.stage_delay_ms > 0:
        await asyncio.sleep(settings.stage_delay_ms / 1000)


# ---------------------------------------------------------------- actions (idempotent, retried, labeled)

def _transient(error: Exception) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in (408, 429) or error.response.status_code >= 500
    return isinstance(error, (httpx.TimeoutException, httpx.TransportError))


async def execute_action(dispute: Dispute, action: str, order: Order | None, shipment: Shipment | None, packet: str) -> dict:
    """Run FIGHT or REFUND through the configured adapter. Transient failures retry (max 2) and then raise
    ActionFailed; sandbox gaps (unsupported call, 4xx) fall back to the labeled mock."""
    adapter = get_adapter()
    request_id = f"{dispute.id}:{action}"
    capture_id = order.paypal_capture_id if order else ""
    tracking = {"carrier_name": "OTHER", "tracking_number": shipment.tracking} if shipment else None
    started = time.perf_counter()
    last_error: Exception | None = None
    for attempt in range(settings.action_max_retries + 1):
        try:
            if action == "FIGHT":
                result = await adapter.provide_evidence(dispute.paypal_dispute_id, packet, tracking)
            else:
                result = await adapter.refund_capture(capture_id, dispute.amount, dispute.currency, "Verdict automated dispute resolution", request_id)
            result["simulated"] = bool(adapter.simulated)
            result["duration_ms"] = round((time.perf_counter() - started) * 1000)
            return {"action": action, "simulated": result["simulated"], "result": result, "duration_ms": result["duration_ms"], "attempts": attempt + 1}
        except UnsupportedInSandbox as error:
            last_error = error
            break
        except httpx.HTTPError as error:
            last_error = error
            if _transient(error) and attempt < settings.action_max_retries:
                await asyncio.sleep(0.4 * (attempt + 1))
                continue
            if _transient(error):
                raise ActionFailed(f"PayPal {action} failed after {attempt + 1} attempts: {error}") from error
            break
    fallback = MockPayPalAdapter()
    mock = await (fallback.provide_evidence(dispute.paypal_dispute_id, packet, tracking) if action == "FIGHT" else fallback.refund_capture(capture_id, dispute.amount, dispute.currency, "SIMULATED sandbox fallback", request_id))
    mock["simulated"] = True
    return {"action": action, "simulated": True, "fallback_reason": f"Sandbox could not complete this call, used labeled mock: {last_error}", "result": mock, "duration_ms": round((time.perf_counter() - started) * 1000), "attempts": 1}


async def perform_action(db: Session, dispute: Dispute, action: str, packet: str) -> dict:
    """Exactly-once per (dispute, action): the idempotency key is claimed before the adapter is called."""
    key = f"{dispute.id}:{action}"
    claim = Action(dispute_id=dispute.id, action_type=action, idempotency_key=key, result_json={"status": "PENDING"}, simulated=True)
    db.add(claim)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Action).where(Action.idempotency_key == key))
        return {"action": action, "already_executed": True, "simulated": bool(existing.simulated) if existing else True, "result": existing.result_json if existing else {}}
    try:
        order, shipment = db.get(Order, dispute.order_id), db.get(Shipment, dispute.order_id)
        result = await execute_action(dispute, action, order, shipment, packet)
    except Exception:
        db.delete(claim)  # release the claim so a retry or the human path can proceed
        db.commit()
        raise
    claim.result_json, claim.simulated = jsonable(result), bool(result["simulated"])
    db.commit()
    return result


# ---------------------------------------------------------------- the pipeline

async def run_pipeline(dispute_id: str) -> None:
    db = SessionLocal()
    try:
        await _run(db, dispute_id)
    except Exception as error:  # never leave a case half-processed: escalate with the error logged
        db.rollback()
        await _escalate_on_error(db, dispute_id, error)
    finally:
        db.close()


async def _escalate_on_error(db: Session, dispute_id: str, error: Exception) -> None:
    dispute = db.get(Dispute, dispute_id)
    if not dispute or dispute.status in {"EVIDENCE_SUBMITTED", "REFUNDED", "RESOLVED", "EXPIRED"}:
        return
    message = f"{type(error).__name__}: {error}"[:500]
    if not db.scalar(select(Approval).where(Approval.dispute_id == dispute.id)):
        db.add(Approval(dispute_id=dispute.id, requested_action="REFUND", recommendation_summary=f"Automated handling failed and the case was escalated. Error: {message}", status="PENDING"))
    decision = db.scalar(select(Decision).where(Decision.dispute_id == dispute.id))
    if decision:
        decision.final_action, decision.guardrail_rule = "ESCALATE", decision.guardrail_rule or "PIPELINE_ERROR"
    else:
        db.add(Decision(dispute_id=dispute.id, policy_decision="ESCALATE", rule_fired="PIPELINE_ERROR", guardrail_rule="PIPELINE_ERROR", final_action="ESCALATE"))
    dispute.status = "AWAITING_APPROVAL"
    db.commit()
    log(db, dispute, "LOG", "Pipeline error; case escalated for merchant review", output_json={"error": message})
    announce(db, dispute, ["status", "decision"])


async def _run(db: Session, dispute_id: str) -> None:
    dispute = db.get(Dispute, dispute_id)
    if not dispute or dispute.status != "NEW":
        return  # the pipeline runs once per dispute
    pipeline_started = time.perf_counter()
    merchant_settings = settings_for(db)
    thr = thresholds(merchant_settings)
    dispute.status = "ASSESSING"
    db.commit()
    announce(db, dispute, ["status"])

    # GATHER
    started = time.perf_counter()
    gathered = gather(db, dispute, merchant_settings.shipping_policy_text)
    log(db, dispute, "GATHER", f"{len(gathered.tool_calls)} evidence tools ran" + (" (some evidence missing)" if gathered.missing_evidence else ""), output_json={"tool_calls": gathered.tool_calls, "checks": gathered.context["checks"]}, started=started)
    await _pause()

    # ASSESS
    started = time.perf_counter()
    result, output, llm_error = await run_assessment(gathered.evidence, gathered.context)
    order, shipment = db.get(Order, dispute.order_id), db.get(Shipment, dispute.order_id)
    messages = list(db.scalars(select(Message).where(Message.order_id == dispute.order_id).order_by(Message.ts, Message.id)).all())
    narrative = output.packet_draft if output else ""
    rationale = output.rationale if output else "The model assessment failed after retries, so the deterministic checklist stands alone and the case needs merchant review."
    assessment = Assessment(dispute_id=dispute.id, evidence_json=result["evidence_items"], conflicts_json=result["conflicts"], checklist_score=result["checklist_score"], win_likelihood=result["win_likelihood"], confidence=result["confidence"], recommended="ESCALATE", rationale=rationale, packet_draft="", llm_error=llm_error, token_usage=output.token_usage if output else None)
    assessment.packet_draft = build_packet(dispute, order, shipment, messages, assessment, narrative, merchant_settings.shipping_policy_text)
    db.add(assessment)
    db.commit()
    announce(db, dispute, ["win_likelihood"])
    log(db, dispute, "ASSESS", f"Win likelihood {result['win_likelihood']:.0%}, confidence {result['confidence']:.0%}" + (f"; LLM error: {llm_error}" if llm_error else ""), input_json={"context": gathered.context}, output_json={**{k: v for k, v in result.items() if k != "evidence_items"}, "llm_recommended": output.recommended if output else None, "llm_error": llm_error, "token_usage": output.token_usage if output else None}, started=started)
    await _pause()

    # DECIDE + GUARD
    expired = is_expired(dispute.deadline)
    started = time.perf_counter()
    decision = decide_and_guard(result, dispute.amount, expired, thr, gathered.missing_evidence)
    assessment.recommended = decision["recommendation"]
    db.add(Decision(dispute_id=dispute.id, policy_decision=decision["recommendation"], rule_fired=decision["rule_fired"], guardrail_rule=decision["guardrail_rule"], final_action=decision["final_action"]))
    db.commit()
    log(db, dispute, "DECIDE", f"Policy chose {decision['recommendation']} (rule {decision['rule_fired']})", input_json={"thresholds": thr, "win_likelihood": result["win_likelihood"], "confidence": result["confidence"]}, output_json={"recommendation": decision["recommendation"], "rule_fired": decision["rule_fired"]}, started=started)
    log(db, dispute, "GUARD", f"Guardrail {decision['guardrail_rule']} changed {decision['recommendation']} to {decision['final_action']}" if decision["guardrail_rule"] else f"No guardrail triggered; {decision['final_action']} stands", input_json={"amount": dispute.amount, "deadline": dispute.deadline, "expired": expired, "conflicts": result["conflicts"]}, output_json=decision)
    await _pause()

    # ACT
    final_action = decision["final_action"]
    started = time.perf_counter()
    if final_action == "EXPIRED":
        dispute.status = "EXPIRED"
        db.commit()
        log(db, dispute, "ACT", "Deadline expired: no action taken; merchant notified", started=started)
        event_bus.publish("notification", {"dispute_id": dispute.id, "level": "warning", "message": f"Dispute {dispute.id} passed its response deadline. No action was taken."})
    elif final_action in FINAL_STATUS:
        try:
            outcome = await perform_action(db, dispute, final_action, assessment.packet_draft)
        except ActionFailed as error:
            raise error  # escalated with the error logged by run_pipeline
        dispute.status, dispute.resolved_at = FINAL_STATUS[final_action], datetime.now(timezone.utc)
        db.commit()
        log(db, dispute, "ACT", f"{'Submitted evidence packet' if final_action == 'FIGHT' else 'Issued refund'}{' (SIMULATED)' if outcome.get('simulated') else ''}", output_json=outcome, started=started)
    else:
        requested = lean_action(result["win_likelihood"]) if not gathered.missing_evidence else "REFUND"
        urgent = is_urgent(dispute.deadline)
        db.add(Approval(dispute_id=dispute.id, requested_action=requested, status="PENDING", recommendation_summary=(("URGENT: under 24 hours left. " if urgent else "") + rationale)))
        dispute.status = "AWAITING_APPROVAL"
        db.commit()
        log(db, dispute, "ACT", f"Approval requested for {requested}" + (" (URGENT, under 24h left)" if urgent else ""), output_json={"requested_action": requested, "urgent": urgent}, started=started)

    # LOG
    log(db, dispute, "LOG", "Case processed", output_json={"status": dispute.status, "final_action": final_action, "total_ms": round((time.perf_counter() - pipeline_started) * 1000)})
    announce(db, dispute, ["status", "decision", "win_likelihood"])


# ---------------------------------------------------------------- human approval flow

async def approve(db: Session, dispute_id: str, note: str | None = None, decided_by: str = "demo merchant", override_action: str | None = None) -> Dispute:
    dispute = db.get(Dispute, dispute_id)
    approval = db.scalar(select(Approval).where(Approval.dispute_id == dispute_id))
    if not dispute or not approval or approval.status != "PENDING":
        raise RuleError("ALREADY_PROCESSED", "Approval is no longer pending")
    if is_expired(dispute.deadline):
        raise RuleError("GUARDRAIL_BLOCKED", "Dispute deadline has expired")
    action = override_action or approval.requested_action
    if action not in FINAL_STATUS:
        raise RuleError("INVALID_STATE", f"Cannot execute {action}", 422)
    claimed = db.execute(update(Approval).where(Approval.id == approval.id, Approval.status == "PENDING").values(status="APPROVED", decided_at=datetime.now(timezone.utc), decided_by=decided_by, note=note))
    db.commit()
    if claimed.rowcount != 1:
        raise RuleError("ALREADY_PROCESSED", "Approval is no longer pending")
    assessment = db.scalar(select(Assessment).where(Assessment.dispute_id == dispute_id))
    started = time.perf_counter()
    try:
        outcome = await perform_action(db, dispute, action, assessment.packet_draft if assessment else "")
    except Exception as error:
        db.execute(update(Approval).where(Approval.id == approval.id).values(status="PENDING", decided_at=None, decided_by=None))
        db.commit()
        log(db, dispute, "ACT", f"Approved {action} failed: {error}", output_json={"error": str(error)}, started=started)
        raise RuleError("UPSTREAM_ERROR", f"PayPal action failed: {error}", 502) from error
    dispute.status, dispute.resolved_at = FINAL_STATUS[action], datetime.now(timezone.utc)
    decision = db.scalar(select(Decision).where(Decision.dispute_id == dispute_id))
    if decision:
        decision.final_action = f"{action}_APPROVED"
    db.commit()
    log(db, dispute, "ACT", f"Approved by {decided_by}: {'submitted evidence packet' if action == 'FIGHT' else 'issued refund'}{' (SIMULATED)' if outcome.get('simulated') else ''}", input_json={"note": note, "override_action": override_action}, output_json=outcome, started=started)
    announce(db, dispute, ["status", "decision"])
    return dispute


def reject(db: Session, dispute_id: str, note: str | None = None, decided_by: str = "demo merchant") -> Dispute:
    dispute = db.get(Dispute, dispute_id)
    approval = db.scalar(select(Approval).where(Approval.dispute_id == dispute_id))
    if not dispute or not approval or approval.status != "PENDING":
        raise RuleError("ALREADY_PROCESSED", "Approval is no longer pending")
    claimed = db.execute(update(Approval).where(Approval.id == approval.id, Approval.status == "PENDING").values(status="REJECTED", decided_at=datetime.now(timezone.utc), decided_by=decided_by, note=note))
    if claimed.rowcount != 1:
        db.rollback()
        raise RuleError("ALREADY_PROCESSED", "Approval is no longer pending")
    dispute.status, dispute.resolved_at = "RESOLVED", datetime.now(timezone.utc)
    db.commit()
    log(db, dispute, "ACT", "Merchant rejected the recommendation; no action taken", input_json={"note": note})
    announce(db, dispute, ["status"])
    return dispute
