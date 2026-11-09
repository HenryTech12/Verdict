# One fully real dispute, end to end (PayPal sandbox)

Goal: a real sandbox payment, a real dispute opened by a sandbox buyer, a real PayPal webhook into Verdict,
and a real refund or evidence call. Record this for the demo video and quote the real IDs in the audit log.

**Prerequisites:** Verdict deployed with `PAYPAL_MODE=sandbox`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`,
`PAYPAL_WEBHOOK_ID` set, and a webhook registered for the three Customer dispute events (see README).
You also need a sandbox **Personal** (buyer) account from the PayPal developer dashboard, under Testing tools,
then Sandbox accounts.

## Steps (run from `backend/`, with PayPal credentials in `.env`)

0. **Confirm your credentials work** (fixes `invalid_client`): `python scripts/check_paypal_credentials.py`. See `docs/PAYPAL_CREDENTIALS.md`.
1. **Create a real sandbox order**
   ```bash
   python scripts/sandbox_order.py create --case B
   ```
   Open the printed link, log in as the sandbox **buyer**, and approve the payment.
2. **Capture it and link Verdict's store data to the real capture id**
   ```bash
   python scripts/sandbox_order.py capture ORDER_ID --case B --api https://YOUR-API.onrender.com --token YOUR_API_TOKEN
   ```
   This prints a **real capture id** and seeds the matching order, shipment and messages in Verdict. Case B has
   a delivery-address mismatch (the agent refunds); use `--case A` for an easy fight or `--case C` ($480) for the approval flow.
3. **Open a real dispute.** Log in to sandbox.paypal.com as the buyer, open the payment in the Resolution Center
   and report that the item was not received. PayPal sends `CUSTOMER.DISPUTE.CREATED` to your webhook.
4. **Watch Verdict handle it.** The dispute appears on the dashboard with no SIM tag. Open the row and check the
   ACT step in the audit timeline: it says whether the refund or evidence call was real or fell back to the labeled mock.

## What is verified and what is not

* The scripts, the `/sim/store-order` endpoint and the linking logic are covered by automated tests with PayPal mocked out.
* **Not verified against live PayPal:** the order approval link format, whether the sandbox Resolution Center lets your
  buyer open a dispute on a sandbox payment, the exact `seller_transaction_id` PayPal sends in the webhook, and whether
  provide-evidence succeeds for that dispute. If a step differs from this document, fix the document and tell us what you saw.
* If the refund or evidence call is rejected by PayPal, Verdict falls back to the labeled mock and records the reason in
  `fallback_reason`. Say so in the submission rather than hiding it.
