from app.llm.base import AssessmentOutput, EvidenceOutput


class MockLLMProvider:
    async def assess(self, case_context: dict[str, object]) -> AssessmentOutput:
        delivered = bool(case_context.get("tracking_delivered"))
        address_match = bool(case_context.get("address_match"))
        proof = bool(case_context.get("delivery_proof"))
        communication = bool(case_context.get("customer_communication"))
        policy = bool(case_context.get("policy_accepted"))
        conflicts = ["Tracking says delivered but delivery address does not match the order address"] if delivered and not address_match else []
        win = 0.9 if delivered and address_match else 0.2
        return AssessmentOutput(
            evidence_items=[
                EvidenceOutput(type="TRACKING_DELIVERED", present=delivered, strength=0.9 if delivered else 0, note="Carrier tracking status"),
                EvidenceOutput(type="ADDRESS_MATCH", present=address_match, strength=0.9 if address_match else 0, note="Delivery address comparison"),
                EvidenceOutput(type="DELIVERY_PROOF", present=proof, strength=0.9 if proof else 0, note="Signature or delivery photo"),
                EvidenceOutput(type="CUSTOMER_COMMUNICATION", present=communication, strength=0.9 if communication else 0, note="Message history"),
                EvidenceOutput(type="POLICY_ACCEPTED", present=policy, strength=0.9 if policy else 0, note="Order policy acceptance"),
            ],
            conflicts=conflicts,
            win_likelihood=win,
            confidence=0.86,
            recommended="REFUND" if conflicts else "FIGHT",
            rationale="Conflict detected; do not fight delivery to a mismatched address." if conflicts else "Evidence supports fighting the dispute.",
            packet_draft="SIMULATED evidence packet based only on the supplied case context.",
        )
