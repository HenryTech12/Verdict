"""Deterministic offline stand-in for the LLM. It reads the same context a real model would
(including message text) and returns the same structured output."""
from app.llm.base import AssessmentOutput, EvidenceOutput

DISPUTED_LOCATION_HINTS = ("wrong address", "different address", "not my address", "neighbor", "neighbour", "someone else")


class MockLLMProvider:
    async def assess(self, case_context: dict[str, object]) -> AssessmentOutput:
        checks = dict(case_context.get("checks") or {})  # type: ignore[arg-type]
        dispute = dict(case_context.get("dispute") or {})  # type: ignore[arg-type]
        shipment = case_context.get("shipment") or {}
        messages = list(case_context.get("messages") or [])  # type: ignore[arg-type]
        not_as_described = dispute.get("reason") == "NOT_AS_DESCRIBED"
        delivered, address_match, proof = (bool(checks.get(k)) for k in ("tracking_delivered", "address_match", "delivery_proof"))
        matches_listing = bool(checks.get("matches_listing", True))
        pack_photo = bool(checks.get("pack_photo"))

        conflicts: list[str] = []
        customer_text = " ".join(str(m.get("text", "")).lower() for m in messages if m.get("sender") == "customer")  # type: ignore[union-attr]
        if any(hint in customer_text for hint in DISPUTED_LOCATION_HINTS):
            conflicts.append("Customer message disputes the delivery location")

        if not_as_described:
            strong = delivered and matches_listing
            win = (0.85 if pack_photo else 0.65) if strong else 0.2
            rationale = (
                f"Carrier shows the order delivered; the shipped item matches the listing{' and a pre-shipment packing photo is on file' if pack_photo else ' but there is no packing photo'}."
                if strong else "The order record does not support that the shipped item matched the listing, so fighting is unlikely to succeed."
            )
        else:
            strong = delivered and address_match
            win = 0.9 if strong and proof else 0.75 if strong else 0.2
            if delivered and not address_match:
                rationale = f"Tracking shows delivery on {shipment.get('delivered_at')} but to {shipment.get('delivery_address')}, which does not match the order address. Fighting would put a visibly weak case in front of PayPal, so refunding is the better call."  # type: ignore[union-attr]
            elif strong:
                rationale = f"Carrier shows delivery on {shipment.get('delivered_at')} to the order address{' with a delivery photo or signature' if proof else ''}; customer messages and policy acceptance back this up."  # type: ignore[union-attr]
            else:
                rationale = "Delivery evidence is incomplete, so the case is weak."
        if conflicts:
            win = min(win, 0.5)
        items = [
            EvidenceOutput(type=str(k).upper(), present=bool(v), strength=0.9 if v else 0, note=str(k).replace("_", " ").capitalize())
            for k, v in checks.items()
        ]
        packet = (
            "The merchant shipped the order and can document delivery. "
            + ("Carrier tracking confirms delivery to the address on the order. " if delivered and address_match else "")
            + ("A delivery photo or signature is attached. " if proof else "")
            + ("A pre-shipment packing photo shows the item as listed. " if pack_photo else "")
            + "Message history with the customer is included."
        )
        return AssessmentOutput(
            evidence_items=items,
            conflicts=conflicts,
            win_likelihood=win,
            confidence=0.86 if checks else 0.4,
            recommended="FIGHT" if win >= 0.6 else "REFUND" if win < 0.35 else "ESCALATE",
            rationale=rationale,
            packet_draft=packet,
        )
