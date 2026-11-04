from decimal import Decimal

import httpx

from app.adapters.paypal_base import UnsupportedInSandbox
from app.config import settings


class SandboxPayPalAdapter:
    def __init__(self) -> None:
        if settings.paypal_base_url != "https://api-m.sandbox.paypal.com":
            raise ValueError("Only the PayPal sandbox base URL is allowed")
        self._token: str | None = None

    async def _access_token(self) -> str:
        # verify against current PayPal docs
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{settings.paypal_base_url}/v1/oauth2/token", auth=(settings.paypal_client_id or "", settings.paypal_client_secret or ""), data={"grant_type": "client_credentials"})
            response.raise_for_status()
            self._token = response.json()["access_token"]
            return self._token

    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        # verify against current PayPal docs
        token = self._token or await self._access_token()
        payload = {"auth_algo": headers.get("PAYPAL-AUTH-ALGO"), "cert_url": headers.get("PAYPAL-CERT-URL"), "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID"), "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG"), "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME"), "webhook_id": settings.paypal_webhook_id, "webhook_event": body.decode("utf-8")}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{settings.paypal_base_url}/v1/notifications/verify-webhook-signature", headers={"Authorization": f"Bearer {token}"}, json=payload)
            response.raise_for_status()
            return response.json().get("verification_status") == "SUCCESS"

    async def get_dispute(self, dispute_id: str) -> dict:
        # verify against current PayPal docs
        token = self._token or await self._access_token()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{settings.paypal_base_url}/v1/customer/disputes/{dispute_id}", headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
            return response.json()

    async def provide_evidence(self, dispute_id: str, packet: str) -> dict:
        raise UnsupportedInSandbox("Evidence submission support must be verified against current sandbox behavior")

    async def refund_capture(self, capture_id: str, amount: Decimal, currency: str, note: str, request_id: str) -> dict:
        # verify against current PayPal docs
        token = self._token or await self._access_token()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{settings.paypal_base_url}/v2/payments/captures/{capture_id}/refund", headers={"Authorization": f"Bearer {token}", "PayPal-Request-Id": request_id}, json={"amount": {"value": str(amount), "currency_code": currency}, "note_to_payer": note})
            response.raise_for_status()
            return response.json()
