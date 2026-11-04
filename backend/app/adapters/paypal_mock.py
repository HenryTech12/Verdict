from decimal import Decimal


class MockPayPalAdapter:
    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        return True

    async def get_dispute(self, dispute_id: str) -> dict:
        return {"id": dispute_id, "simulated": True, "status": "OPEN"}

    async def provide_evidence(self, dispute_id: str, packet: str) -> dict:
        return {"dispute_id": dispute_id, "status": "EVIDENCE_SUBMITTED", "simulated": True}

    async def refund_capture(self, capture_id: str, amount: Decimal, currency: str, note: str, request_id: str) -> dict:
        return {"capture_id": capture_id, "amount": str(amount), "currency": currency, "status": "REFUNDED", "simulated": True, "request_id": request_id}
