"""Create a REAL PayPal sandbox payment and link it to Verdict, for an end-to-end real dispute flow.

Step 1  python scripts/sandbox_order.py create --case B
        Creates a sandbox order and prints a buyer approval link. Open it and log in with your sandbox
        PERSONAL (buyer) account, then approve the payment.
Step 2  python scripts/sandbox_order.py capture ORDER_ID --case B --api https://YOUR-API.onrender.com --token YOUR_API_TOKEN
        Captures the payment (real capture id) and seeds matching store data in Verdict.
Step 3  Log in to sandbox.paypal.com as the buyer, open the payment in Resolution Center and report
        "I didn't receive my item". PayPal sends CUSTOMER.DISPUTE.CREATED to your webhook and Verdict handles it.

Needs PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env. Only talks to api-m.sandbox.paypal.com."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.config import SANDBOX_URL, settings  # noqa: E402

AMOUNTS = {"A": "80.00", "B": "90.00", "C": "480.00", "D": "70.00", "E": "300.00", "F": "55.00"}


def token(client: httpx.Client) -> dict[str, str]:
    if not (settings.paypal_client_id and settings.paypal_client_secret):
        sys.exit("Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env first.")
    response = client.post(f"{SANDBOX_URL}/v1/oauth2/token", auth=(settings.paypal_client_id, settings.paypal_client_secret), data={"grant_type": "client_credentials"})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create(args: argparse.Namespace) -> None:
    amount = args.amount or AMOUNTS[args.case]
    with httpx.Client(timeout=30) as client:
        headers = token(client)
        response = client.post(f"{SANDBOX_URL}/v2/checkout/orders", headers=headers, json={
            "intent": "CAPTURE",
            "purchase_units": [{"description": f"Verdict demo order (case {args.case})", "amount": {"currency_code": "USD", "value": amount}}],
            "payment_source": {"paypal": {"experience_context": {"user_action": "PAY_NOW", "return_url": "https://example.com/return", "cancel_url": "https://example.com/cancel"}}},
        })
        if response.status_code not in (200, 201):
            sys.exit(f"Create order failed: {response.status_code} {response.text}")
        body = response.json()
    link = next((item["href"] for item in body.get("links", []) if item["rel"] in ("payer-action", "approve")), None)
    print(f"Order id: {body['id']}  amount: ${amount}\nApprove it as your sandbox BUYER:\n  {link}\nThen run: python scripts/sandbox_order.py capture {body['id']} --case {args.case} --api <API URL> --token <API TOKEN>")


def capture(args: argparse.Namespace) -> None:
    with httpx.Client(timeout=30) as client:
        response = client.post(f"{SANDBOX_URL}/v2/checkout/orders/{args.order_id}/capture", headers={**token(client), "Content-Type": "application/json", "PayPal-Request-Id": f"verdict-capture-{args.order_id}"})
        if response.status_code not in (200, 201):
            sys.exit(f"Capture failed ({response.status_code}). Did you approve the order as the buyer? {response.text[:300]}")
        capture_id = response.json()["purchase_units"][0]["payments"]["captures"][0]["id"]
        print(f"Real capture id: {capture_id}")
        seeded = client.post(f"{args.api.rstrip('/')}/sim/store-order", params={"case": args.case, "capture_id": capture_id}, headers={"Authorization": f"Bearer {args.token}"})
        if seeded.status_code != 201:
            sys.exit(f"Verdict store seeding failed: {seeded.status_code} {seeded.text}")
        print(f"Verdict now has matching store data ({seeded.json()['order_id']}, case {args.case}).")
    print("Next: as the sandbox buyer, report 'item not received' on this payment in Resolution Center, then watch the dashboard.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create"); c.add_argument("--case", default="B", choices=sorted(AMOUNTS)); c.add_argument("--amount"); c.set_defaults(run=create)
    k = sub.add_parser("capture"); k.add_argument("order_id"); k.add_argument("--case", default="B", choices=sorted(AMOUNTS)); k.add_argument("--api", default="http://localhost:8000"); k.add_argument("--token", default=settings.api_token); k.set_defaults(run=capture)
    parsed = parser.parse_args()
    parsed.run(parsed)
