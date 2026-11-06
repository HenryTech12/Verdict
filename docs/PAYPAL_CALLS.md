# Which PayPal calls are real and which are simulated

Verdict is a prototype, not an official PayPal product. Default mode is `PAYPAL_MODE=mock`; set
`PAYPAL_MODE=sandbox` for real sandbox calls (the base URL is pinned to `https://api-m.sandbox.paypal.com`).

| Capability | Mock mode (default) | Sandbox mode |
|---|---|---|
| Webhook signature verification | **Simulated**: HMAC-SHA256 from the built-in simulator, header `X-Verdict-Sim-Signature` | **Real**: `POST /v1/notifications/verify-webhook-signature` with the PayPal transmission headers |
| Dispute created / updated / resolved events | **Simulated**: signed payloads posted to our own `/webhooks/paypal` | Real events if a webhook is registered; the simulator still works |
| Provide evidence | **Simulated** | **Real call implemented**: `POST /v1/customer/disputes/{id}/provide-evidence` (multipart `input`, `PROOF_OF_FULFILLMENT` with tracking). Succeeds only for a real dispute awaiting the seller; otherwise falls back to the labeled mock |
| Refund | **Simulated** | **Real call implemented**: `POST /v2/payments/captures/{id}/refund` with a `PayPal-Request-Id` idempotency header. Needs a real sandbox capture id; otherwise falls back to the labeled mock |

Every audit entry and action result carries a `simulated` flag, the dashboard shows `PAYPAL: MOCK` or
`PAYPAL: SANDBOX` plus SIM tags, and fallbacks record `fallback_reason`.

## Verified against PayPal docs

* Provide evidence is `multipart/form-data` with an `input` JSON field (`evidences[].evidence_type`, `evidence_info.tracking_info`, `notes`) and applies to disputes in `WAITING_FOR_SELLER_RESPONSE`.

## Not yet verified live (do this on day 1 of real integration)

The sandbox calls above were written to PayPal's documented shapes but **have not been exercised against a live
sandbox account in this repository's test run**. Run the capability check with your own credentials and paste the
matrix into this file before submitting:

```bash
cd backend && python scripts/sandbox_spike.py [capture_id] [dispute_id]
```

## Standalone sandbox checkout UI

The frontend `/payments` route loads the PayPal JavaScript SDK using the public sandbox Client ID returned by `GET /paypal/config`. The backend keeps the Client Secret server-side and implements:

- `POST /paypal/orders` — creates a USD sandbox order (maximum $5,000).
- `POST /paypal/orders/{order_id}/capture` — captures an order after buyer approval.

These checkout endpoints are separate from the dispute pipeline. They return `SANDBOX_REQUIRED` when `PAYPAL_MODE=mock`; they never simulate a successful payment. Use only PayPal sandbox buyer and merchant accounts. A successful checkout capture does not automatically create a dispute or attach the capture to an order; use the existing `/sim/store-order` workflow to link a real capture to seeded store data before testing a real dispute webhook.
