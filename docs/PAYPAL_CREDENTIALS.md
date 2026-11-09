# PayPal sandbox credentials: fixing `invalid_client`

`invalid_client` comes from PayPal's OAuth token endpoint. It means PayPal rejected the Client ID and Secret.
Until the token call works, every PayPal action in Verdict falls back to the clearly labeled mock, and the audit
entry shows the reason (for example `PayPal OAuth rejected the sandbox credentials (invalid_client: ...)`).

## Check the credentials without the app

From `backend/` (reads `.env` or your environment; never prints the secret):

```bash
python scripts/check_paypal_credentials.py
```

It prints `OK` when PayPal accepts them, or the exact reason when it does not. To test the same thing by hand:

```bash
curl -s -u "CLIENT_ID:CLIENT_SECRET" -d grant_type=client_credentials https://api-m.sandbox.paypal.com/v1/oauth2/token
```

A JSON body with `access_token` means the credentials are good.

## Most likely causes, in order

1. **Live credentials against the sandbox URL.** In the PayPal Developer Dashboard, open *Apps & Credentials* and make
   sure the **Sandbox** toggle is selected before you create or copy an app. Verdict only talks to `api-m.sandbox.paypal.com`.
2. **Stray characters.** A space, quote or line break pasted with the key. Verdict now trims whitespace and quotes from
   `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID` and `GROQ_API_KEY`, but a truncated or altered value still fails.
3. **ID and secret from different apps**, or a secret that was regenerated after you copied it.
4. **The wrong environment on the host.** Render uses its own environment settings, not your local `.env`. Re-enter the
   values there and redeploy.

## After it works

Run `python scripts/sandbox_spike.py` and paste the matrix into `docs/PAYPAL_CALLS.md`, then follow
`docs/REAL_SANDBOX_FLOW.md`.
