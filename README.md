# Verdict

Verdict is a mock-first AI dispute operations console for small online merchants. It gathers delivery evidence, scores whether an item-not-received case is winnable, and chooses `FIGHT`, `REFUND`, or `ESCALATE` inside code-enforced guardrails.

## Run locally

The demo works without paid keys. Use Python 3.11+ and Node.js 20+:

```bash
cd backend
python -m pip install -e ".[test]"
python -m pytest -q
python -m uvicorn app.main:app --reload --port 8000
# in another terminal, from the repository root
cd ..
npm run dev
```

Open `http://localhost:3000`. The API docs are at `http://localhost:8000/docs`. Run Case A, B, or C from the dashboard. All simulator data and mock PayPal behavior are labeled `SIMULATED`.

## Environment variables

Copy `.env.example` to `.env`. For the offline demo, keep `PAYPAL_MODE=mock` and `LLM_PROVIDER=mock`; no PayPal credentials or LLM key are required. The frontend uses `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_API_TOKEN`, and optionally `NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY`.

For the intended Groq setup, use `LLM_PROVIDER=groq`, set `GROQ_API_KEY`, and choose `LLM_MODEL` (for example `llama-3.3-70b-versatile`). The provider boundary is implemented under `backend/app/llm`; the pipeline still defaults to the deterministic mock assessment until the orchestration wiring is enabled.

PayPal sandbox credentials are only needed for a future real integration: `PAYPAL_MODE=sandbox`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, and the fixed sandbox URL in `PAYPAL_BASE_URL`. Never use live PayPal credentials or a live base URL.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
