from decimal import Decimal
from typing import Protocol


class UnsupportedInSandbox(RuntimeError):
    pass


class PayPalAdapter(Protocol):
    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        ...

    async def get_dispute(self, dispute_id: str) -> dict:
        ...

    async def provide_evidence(self, dispute_id: str, packet: str) -> dict:
        ...

    async def refund_capture(self, capture_id: str, amount: Decimal, currency: str, note: str, request_id: str) -> dict:
        ...
