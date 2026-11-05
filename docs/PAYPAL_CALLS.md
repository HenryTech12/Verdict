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
