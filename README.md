# Verdict

Verdict is a mock-first AI dispute operations console for small online merchants. It gathers delivery evidence, scores whether an item-not-received case is winnable, and chooses `FIGHT`, `REFUND`, or `ESCALATE` inside code-enforced guardrails.

## Run locally

The demo works without paid keys. Use Python 3.11+ and Node.js 20+:

```bash
cd backend && python -m pip install -e ".[test]" && cd ..
make test
python -m uvicorn backend.app.main:app --reload --port 8000
# in another terminal
npm run dev
```

Open `http://localhost:3000`. The API docs are at `http://localhost:8000/docs`. Run Case A, B, or C from the dashboard. All simulator data and mock PayPal behavior are labeled `SIMULATED`.

## Environment variables

Copy `.env.example` to `.env`. For the offline demo, keep `PAYPAL_MODE=mock` and `LLM_PROVIDER=mock`; no PayPal credentials or LLM key are required. The frontend uses `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_API_TOKEN`, and optionally `NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY`.

For the intended Groq setup, use `LLM_PROVIDER=groq`, set `GROQ_API_KEY`, and choose `LLM_MODEL` (for example `llama-3.3-70b-versatile`). The current deterministic mock assessment remains active because the Groq adapter and server-side AI proxy are not yet implemented in this repository; setting the variable alone does not make an external Groq call.

PayPal sandbox credentials are only needed for a future real integration: `PAYPAL_MODE=sandbox`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, and the fixed sandbox URL in `PAYPAL_BASE_URL`. Never use live PayPal credentials or a live base URL.

## Demo cases

- Case A: strong evidence, auto-submits evidence (`FIGHT`).
- Case B: delivered address conflict, refunds under the cap (`REFUND`).
- Case C: strong evidence above the approval threshold (`ESCALATE` and approval required).

The backend provides the mock-mode API, SQLite persistence, deterministic assessment, settings, metrics, approval actions, and the core dashboard. PayPal sandbox adapters, real LLM providers, SSE replay, and the full approval/settings screens remain integration work for a later phase; no live credentials are used.

## AG Studio

The dashboard includes AG Studio 3.0.0 with three saved pages, flat analytics sources under `/analytics/*`, and custom read-only Verdict Card, Deadline Risk, and Guardrail Activity widgets. Analytics amount fields are numeric for charting; transactional API money remains decimal strings. Add a licensed key as `NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY` in an ignored `.env.local` file for production. Local development works without it and may show the Studio watermark.

The Agent Framework module is registered, but the server-side LLM proxy and provider adapter are intentionally not enabled until an `LLM_PROVIDER` and server key are configured. No client-side LLM key is used, and Studio has no payment, refund, evidence-submission, approval, or settings-changing tools.

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
