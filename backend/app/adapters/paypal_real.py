"""PayPal sandbox adapter. Calls follow PayPal's Customer Disputes v1 and Payments v2 REST docs.
Sandbox only: the base URL is pinned in config. Which calls actually succeed against sandbox data
is reported by scripts/sandbox_spike.py; failures fall back to the labeled mock in the pipeline."""
import json
from decimal import Decimal

import httpx

from app.config import SANDBOX_URL, settings
from app.adapters.paypal_base import UnsupportedInSandbox


class SandboxPayPalAdapter:
    simulated = False

    def __init__(self) -> None:
        if settings.paypal_base_url != SANDBOX_URL:
            raise ValueError("Only the PayPal sandbox base URL is allowed")
        self._token: str | None = None

    async def _access_token(self) -> str:
        if self._token:
            return self._token
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{SANDBOX_URL}/v1/oauth2/token", auth=(settings.paypal_client_id or "", settings.paypal_client_secret or ""), data={"grant_type": "client_credentials"})
            response.raise_for_status()
            self._token = response.json()["access_token"]
            return self._token

    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        h = {k.lower(): v for k, v in headers.items()}
        token = await self._access_token()
        payload = {
            "auth_algo": h.get("paypal-auth-algo"),
            "cert_url": h.get("paypal-cert-url"),
            "transmission_id": h.get("paypal-transmission-id"),
            "transmission_sig": h.get("paypal-transmission-sig"),
            "transmission_time": h.get("paypal-transmission-time"),
            "webhook_id": settings.paypal_webhook_id,
            "webhook_event": json.loads(body.decode("utf-8")),
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{SANDBOX_URL}/v1/notifications/verify-webhook-signature", headers={"Authorization": f"Bearer {token}"}, json=payload)
            response.raise_for_status()
            return response.json().get("verification_status") == "SUCCESS"

    async def get_dispute(self, dispute_id: str) -> dict:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{SANDBOX_URL}/v1/customer/disputes/{dispute_id}", headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
            return response.json()

    async def provide_evidence(self, dispute_id: str, packet: str, tracking: dict | None = None) -> dict:
        """POST /v1/customer/disputes/{id}/provide-evidence (multipart: `input` JSON plus optional files).
        Needs a dispute in WAITING_FOR_SELLER_RESPONSE that PayPal is requesting evidence for."""
        if not tracking or not tracking.get("tracking_number"):
            raise UnsupportedInSandbox("PROOF_OF_FULFILLMENT evidence needs a tracking number")
        token = await self._access_token()
        evidence = {"evidences": [{"evidence_type": "PROOF_OF_FULFILLMENT", "evidence_info": {"tracking_info": [{"carrier_name": tracking.get("carrier_name", "OTHER"), "tracking_number": tracking["tracking_number"]}]}, "notes": packet[:2000]}]}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{SANDBOX_URL}/v1/customer/disputes/{dispute_id}/provide-evidence", headers={"Authorization": f"Bearer {token}"}, files={"input": (None, json.dumps(evidence), "application/json")})
            response.raise_for_status()
            return {"dispute_id": dispute_id, "status": "EVIDENCE_SUBMITTED", **response.json()}

    async def refund_capture(self, capture_id: str, amount: Decimal, currency: str, note: str, request_id: str) -> dict:
        """POST /v2/payments/captures/{id}/refund. PayPal-Request-Id makes retries idempotent on PayPal's side."""
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{SANDBOX_URL}/v2/payments/captures/{capture_id}/refund", headers={"Authorization": f"Bearer {token}", "PayPal-Request-Id": request_id}, json={"amount": {"value": str(amount), "currency_code": currency}, "note_to_payer": note[:255]})
            response.raise_for_status()
            return response.json()
