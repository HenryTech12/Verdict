"""Day-1 PayPal sandbox capability check. Run:  python scripts/sandbox_spike.py [capture_id] [dispute_id]

Reports which calls work with YOUR sandbox app so the submission can state honestly which calls are real.
Needs PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env. It only talks to api-m.sandbox.paypal.com."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.config import SANDBOX_URL, settings  # noqa: E402


async def main(capture_id: str | None, dispute_id: str | None) -> None:
    if not (settings.paypal_client_id and settings.paypal_client_secret):
        sys.exit("Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env first.")
    rows: list[tuple[str, str, str]] = []
    async with httpx.AsyncClient(timeout=30) as client:
        token_response = await client.post(f"{SANDBOX_URL}/v1/oauth2/token", auth=(settings.paypal_client_id, settings.paypal_client_secret), data={"grant_type": "client_credentials"})
        ok = token_response.status_code == 200
        rows.append(("OAuth token", "REAL" if ok else "FAIL", str(token_response.status_code)))
        if not ok:
            report(rows)
            return
        headers = {"Authorization": f"Bearer {token_response.json()['access_token']}"}

        r = await client.get(f"{SANDBOX_URL}/v1/customer/disputes", headers=headers, params={"page_size": 5})
        rows.append(("List disputes", "REAL" if r.status_code == 200 else "FAIL", f"{r.status_code} {len(r.json().get('items', [])) if r.status_code == 200 else r.text[:120]} items"))
        dispute_id = dispute_id or next(iter((r.json().get("items") or [{}]) if r.status_code == 200 else [{}]), {}).get("dispute_id")

        if dispute_id:
            r = await client.get(f"{SANDBOX_URL}/v1/customer/disputes/{dispute_id}", headers=headers)
            rows.append((f"Show dispute {dispute_id}", "REAL" if r.status_code == 200 else "FAIL", str(r.status_code)))
        else:
            rows.append(("Show / provide-evidence", "SIMULATED", "no sandbox dispute available; create one in the sandbox dashboard and pass its id"))

        r = await client.post(f"{SANDBOX_URL}/v2/checkout/orders", headers={**headers, "PayPal-Request-Id": "verdict-spike-order"}, json={"intent": "CAPTURE", "purchase_units": [{"amount": {"currency_code": "USD", "value": "10.00"}}]})
        approve = next((link["href"] for link in r.json().get("links", []) if link["rel"] in ("approve", "payer-action")), None) if r.status_code in (200, 201) else None
        rows.append(("Create order", "REAL" if r.status_code in (200, 201) else "FAIL", f"{r.status_code}; buyer approval link: {approve}"))

        if capture_id:
            r = await client.post(f"{SANDBOX_URL}/v2/payments/captures/{capture_id}/refund", headers={**headers, "PayPal-Request-Id": "verdict-spike-refund"}, json={"amount": {"value": "1.00", "currency_code": "USD"}})
            rows.append((f"Refund capture {capture_id}", "REAL" if r.status_code in (200, 201) else "FAIL", f"{r.status_code} {r.text[:120]}"))
        else:
            rows.append(("Refund capture", "SIMULATED", "pass a real sandbox capture id as the first argument to test"))
    report(rows)


def report(rows: list[tuple[str, str, str]]) -> None:
    print("\nCapability matrix (copy into docs/PAYPAL_CALLS.md):\n")
    for name, status, detail in rows:
        print(f"  {status:<10} {name:<34} {detail}")
    print("\nSet PAYPAL_MODE=sandbox to use the real calls. Calls that fail fall back to the labeled mock adapter.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None, sys.argv[2] if len(sys.argv) > 2 else None))
