import time
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.adapters.paypal_base import UnsupportedInSandbox
from app.adapters.paypal_mock import MockPayPalAdapter
from app.adapters.paypal_real import SandboxPayPalAdapter
from app.config import settings
from app.llm.base import AssessmentOutput
from app.llm.groq_provider import GroqProvider
from app.llm.mock import MockLLMProvider
from app.services.assessment import CaseEvidence, assess
from app.services.guardrails import apply_guardrails
from app.services.policy import choose_policy


def provider():
    return GroqProvider() if settings.llm_provider == "groq" else MockLLMProvider()


async def evaluate_case(evidence: CaseEvidence, amount: Decimal, deadline_expired: bool, thresholds: dict[str, object]) -> dict:
    context: dict[str, object] = {
        "tracking_delivered": evidence.delivered,
        "address_match": evidence.address_match,
        "delivery_proof": evidence.proof,
        "customer_communication": evidence.communication_strength > 0,
        "policy_accepted": evidence.policy_accepted,
    }
    llm_error: str | None = None
    try:
        output: AssessmentOutput = await provider().assess(context)
    except Exception as error:
        llm_error = str(error)
        output = AssessmentOutput(evidence_items=[], conflicts=[], win_likelihood=0, confidence=0, recommended="ESCALATE", rationale="LLM assessment failed; guardrails require merchant review.", packet_draft="")
    result = assess(evidence, output.win_likelihood, output.confidence)
    result["conflicts"] = sorted(set(result["conflicts"] + output.conflicts))
    if result["conflicts"]:
        result["win_likelihood"] = min(result["win_likelihood"], 0.25)
    recommendation = choose_policy(result["win_likelihood"], result["confidence"], float(thresholds["fight_min_win_likelihood"]), float(thresholds["refund_max_win_likelihood"]), float(thresholds["min_confidence"]))
    final_action, guardrail_rule = apply_guardrails(recommendation, amount, deadline_expired, result["confidence"], result["conflicts"], Decimal(str(thresholds["approval_threshold"])), Decimal(str(thresholds["auto_refund_cap"])), float(thresholds["min_confidence"]))
    result.update({"recommended": recommendation, "rationale": output.rationale, "packet_draft": output.packet_draft, "llm_error": llm_error, "token_usage": output.token_usage})
    return {"assessment": result, "recommendation": recommendation, "final_action": final_action, "guardrail_rule": guardrail_rule}


async def execute_action(dispute_id: str, action: str, capture_id: str, amount: Decimal, currency: str, packet: str) -> dict:
    adapter = SandboxPayPalAdapter() if settings.paypal_mode == "sandbox" else MockPayPalAdapter()
    request_id = f"{dispute_id}:{action}"
    try:
        started = time.perf_counter()
        if action == "FIGHT":
            result = await adapter.provide_evidence(dispute_id, packet)
        elif action == "REFUND":
            result = await adapter.refund_capture(capture_id, amount, currency, "Verdict automated dispute resolution", request_id)
        else:
            return {"action": action, "simulated": True, "result": {"status": "approval_required"}, "duration_ms": 0}
        result["duration_ms"] = round((time.perf_counter() - started) * 1000)
        result["simulated"] = settings.paypal_mode == "mock"
        return {"action": action, "simulated": result["simulated"], "result": result, "duration_ms": result["duration_ms"]}
    except (UnsupportedInSandbox, httpx.HTTPError) as error:
        fallback = MockPayPalAdapter()
        result = await (fallback.provide_evidence(dispute_id, packet) if action == "FIGHT" else fallback.refund_capture(capture_id, amount, currency, "SIMULATED sandbox fallback", request_id))
        return {"action": action, "simulated": True, "fallback_reason": str(error), "result": result, "duration_ms": 0}
