import hashlib
import hmac
from decimal import Decimal

from app.config import settings

SIGNATURE_HEADER = "x-verdict-sim-signature"


def sign_payload(body: bytes) -> str:
    return hmac.new(settings.webhook_sim_secret.encode(), body, hashlib.sha256).hexdigest()


class MockPayPalAdapter:
    """Clearly labeled mock. Webhooks are verified with an HMAC from the built-in simulator."""

    simulated = True

    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        signature = {k.lower(): v for k, v in headers.items()}.get(SIGNATURE_HEADER, "")
        return bool(signature) and hmac.compare_digest(signature, sign_payload(body))

    async def get_dispute(self, dispute_id: str) -> dict:
        return {"id": dispute_id, "simulated": True, "status": "WAITING_FOR_SELLER_RESPONSE"}

    async def provide_evidence(self, dispute_id: str, packet: str, tracking: dict | None = None) -> dict:
        return {"dispute_id": dispute_id, "status": "EVIDENCE_SUBMITTED", "simulated": True}

    async def refund_capture(self, capture_id: str, amount: Decimal, currency: str, note: str, request_id: str) -> dict:
        return {"capture_id": capture_id, "amount": str(amount), "currency": currency, "status": "REFUNDED", "simulated": True, "request_id": request_id}
