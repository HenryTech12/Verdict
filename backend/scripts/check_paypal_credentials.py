"""Check your PayPal sandbox credentials without starting the app.

Run from backend/:  python scripts/check_paypal_credentials.py

Prints whether PayPal accepts the Client ID and Secret from .env or the environment. It never prints the secret.
If you see `invalid_client`, see docs/PAYPAL_CREDENTIALS.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.adapters.paypal_real import auth_hint  # noqa: E402
from app.config import SANDBOX_URL, settings  # noqa: E402


def main() -> int:
    client_id, secret = settings.paypal_client_id, settings.paypal_client_secret
    if not client_id or not secret:
        print("PAYPAL_CLIENT_ID and/or PAYPAL_CLIENT_SECRET are not set (check .env or the environment).")
        return 2
    print(f"Client ID:     {len(client_id)} characters, starts with {client_id[:4]}")
    print(f"Client Secret: {len(secret)} characters")
    try:
        response = httpx.post(f"{SANDBOX_URL}/v1/oauth2/token", auth=(client_id, secret), data={"grant_type": "client_credentials"}, timeout=30)
    except httpx.HTTPError as error:
        print(f"Could not reach PayPal sandbox: {type(error).__name__}")
        return 3
    if response.status_code == 200 and response.json().get("access_token"):
        body = response.json()
        print(f"OK: PayPal accepted the credentials (app_id {body.get('app_id', 'n/a')}, token valid {body.get('expires_in', '?')}s).")
        return 0
    print("FAILED: " + auth_hint(response))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
