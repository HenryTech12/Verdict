# Verdict: know which disputes to fight

Verdict is an AI agent for small online merchants that handles **PayPal payment disputes end to end**. When a
dispute arrives it gathers evidence, scores how winnable the case is, and decides to **FIGHT**, **REFUND** or
**ESCALATE** to the merchant. It acts only inside **hard guardrails enforced in code** (the model cannot override
them), and it logs every decision with its reasoning.

Built as a prototype for the PayPal AI Hackathon. It is **not** an official PayPal product.

> **Honesty note.** By default PayPal calls are served by a clearly labeled **mock adapter** and disputes come from a
> built-in **simulator** that posts signed PayPal-style webhooks to this app's own endpoint. With `PAYPAL_MODE=sandbox`
> the real PayPal sandbox is used where it supports the call. See [docs/PAYPAL_CALLS.md](docs/PAYPAL_CALLS.md) for
> exactly which calls are real and which are simulated, and [docs/REAL_SANDBOX_FLOW.md](docs/REAL_SANDBOX_FLOW.md) to run one fully real dispute end to end.

## Run it (under 10 minutes)

Prerequisites: Python 3.11+, Node 22+. No API keys needed: the defaults are the mock PayPal adapter and the offline LLM stand-in.

```bash
# 1. Backend (terminal 1)
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[test]"
python -m uvicorn app.main:app --port 8000              # seeds 120 simulated historical disputes on first start

# 2. Frontend (terminal 2, repo root)
npm ci
npm run dev                                             # http://localhost:3000
```

Or with Docker: `docker compose up --build` (dashboard on :3000, API on :8000).

Open http://localhost:3000 and click **Case A**, **Case B** and **Case C** in the simulator bar.

Optional: copy `.env.example` to `.env` to use Groq (`LLM_PROVIDER=groq`, `GROQ_API_KEY=...`) or the PayPal sandbox
(`PAYPAL_MODE=sandbox` plus client id/secret/webhook id).

## The three demo cases (acceptance tests)

| Case | Setup | What Verdict does |
|---|---|---|
| **A** Easy fight | Item not received, $80, delivered, address matches, delivery photo | Win likelihood about 90%. **FIGHT**: drafts and submits the evidence packet automatically. |
| **B** Conflict | Item not received, $90, tracking says delivered **but to a different address** | Conflict detected, win likelihood capped at 25%. **REFUND** issued automatically (under the $100 cap). The dashboard shows why the agent chose *not* to fight. |
| **C** High value | Item not received, $480, strong evidence | Policy says FIGHT, but the **guardrail** (amount above the $250 approval threshold) downgrades it to **ESCALATE**. Approve in the dashboard and the packet is submitted. |

Bonus cases: **D** "not as described" (second reason code with its own checklist), **E** urgent deadline (6h left,
flagged URGENT, surfaced first), **F** expired deadline (no action, logged, merchant notified).

## How it works

```
PayPal webhook / simulator
        |  POST /webhooks/paypal   (signature verified, idempotent by event id and dispute id)
        v
 INGEST -> GATHER -> ASSESS -> DECIDE -> GUARD -> ACT -> LOG        every stage = audit row + live SSE event
           tools     checklist  policy    code      adapter
                     + LLM
```

* **Gather**: tools read the order, tracking and delivery proof, address match, customer messages and merchant policy from the database.
* **Assess**: a deterministic checklist score is the backbone. The LLM reads message text and edge details and can only **nudge** the score within +/-0.15. Output is schema-validated; invalid output is retried (max 2) then escalated.
* **Decide**: FIGHT if win >= 0.60 and confidence >= 0.70; REFUND if win < 0.35 and confidence >= 0.70; otherwise ESCALATE. The rule that fired is recorded.
* **Guard**: precedence is *expired > missing evidence > above approval threshold ($250) > refund above auto-refund cap ($100) > low confidence > conflicting evidence (blocks FIGHT)*. Guardrails can only **downgrade**, never upgrade. 482 unit tests pin this, including an exhaustive "never upgrade" property check.
* **Act**: FIGHT submits the evidence packet, REFUND refunds the capture, ESCALATE creates an approval request. Actions are **idempotent**: the idempotency key `dispute:action` is claimed before the adapter is called, so a retry or a double-click cannot refund twice. Transient failures retry twice, then the case is escalated with the error logged.
* **Log**: every step stores timestamp, input, output, rule and action, and is pushed to the dashboard over server-sent events.

Full policy details: [docs/DECISION_POLICY.md](docs/DECISION_POLICY.md).

## Dashboard

* **AG Grid (Community)** dispute table: ID, customer, amount, reason, **deadline countdown** (urgency colors), **win-likelihood bar**, **decision badge**, status.
* Status filter chips with counts, search, sortable columns, and cases that need a human sorted first by soonest deadline.
* **Expandable reasoning row**: click a row for the checklist, conflicts, rationale, rule fired, guardrail explanation, audit timeline, and approve / reject buttons. (Master/detail is an AG Grid Enterprise feature, so this uses Community full-width rows.)
* **Live updates** without refresh over SSE (`/stream`), with a LIVE indicator.
* **Impact panel** with disputes handled, modeled revenue recovered and modeled time saved, labeled *modeled, not measured* with the assumptions shown.
* Approval queue, merchant settings (caps, thresholds, policy text), evidence packet download, scenario lab, and AG Studio analytics pages.


### AG Studio analytics

The analytics section is an AG Studio dashboard built on the same data the agent produces (`/analytics/*`).

* **Typed data model** (`components/studio/model.ts`): every field has a name and format (currency, percentage, date and so on), so charts, filters and the AI analyst use proper labels instead of guessed types.
* **Relationships**: evidence checks, audit steps and guardrail events each belong to one dispute, so a single widget can mix them, for example average evidence strength by dispute status or average pipeline time by decision.
* **Calculated fields**: *Amount at risk* (open cases only) and *Deadline window* (under 24 hours, 1 to 3 days, over 3 days, closed).
* **Three pages** (Overview, Risk and guardrails, Case explorer) with status and decision filters that cross-filter the other widgets, plus three custom widgets (Latest Verdict, Deadline Risk, Guardrail Activity).
* **Self-serve editing**: use *Edit dashboard* to add or rearrange widgets. Changes are saved in your browser and *Reset layout* restores the default. The default layout and field references are checked by `components/studio/model.test.ts`.
* **AI analyst** (when `LLM_PROVIDER=groq`): ask questions in plain language and Studio builds widgets. It is read-only by design: it has no tool that approves, refunds or submits evidence.

### PayPal sandbox checkout

The `/payments` page provides a separate PayPal Checkout sandbox flow for creating and capturing test orders. It is not required for dispute processing. Configure `PAYPAL_MODE=sandbox`, `PAYPAL_CLIENT_ID`, and `PAYPAL_CLIENT_SECRET` on the backend. The browser receives only the public sandbox Client ID; the Client Secret remains server-side. Use PayPal sandbox buyer accounts only.

## API

| Endpoint | Purpose |
|---|---|
| `POST /webhooks/paypal` | Verified, idempotent webhook receiver (created / updated / resolved) |
| `POST /sim/dispute?case=A..F` | Seed store data and fire a signed simulated webhook |
| `GET /disputes`, `GET /disputes/{id}` | Grid data (filters, sort, search) and full detail with audit trail |
| `GET /disputes/{id}/packet` | Download the evidence packet (Markdown) |
| `POST /disputes/{id}/approve`, `/reject` | Human approval flow |
| `GET /stream` | Server-sent events for live updates |
| `GET /PUT /settings` | Per-merchant limits and policy text |
| `GET /metrics` | Modeled impact numbers |

Interactive docs at http://localhost:8000/docs. Requests use `Authorization: Bearer verdict-demo-token` (demo login).

## Tests

```bash
cd backend && python -m pytest -q     # 482 tests: guardrails, policy, scoring, webhooks, idempotency, cases A/B/C x3
npm test && npm run lint              # frontend unit tests + lint
npx tsc --noEmit                      # type check
npm run test:e2e                      # Playwright UI flow (needs `npx playwright install chromium`)
```

Day-one sandbox spike (checks which PayPal calls work with *your* sandbox app): `cd backend && python scripts/sandbox_spike.py`.

## Layout

```
backend/app/services/   assessment, policy, guardrails, gather, pipeline, ingest, simulator, metrics, packet
backend/app/adapters/   PayPal adapter interface, labeled mock, sandbox implementation
backend/app/llm/        provider interface, deterministic mock, Groq provider
backend/tests/          unit + end-to-end acceptance tests
components/grid/        AG Grid table, detail row, impact panel
docs/                   PAYPAL_CALLS.md, DECISION_POLICY.md, SUBMISSION.md, ASSUMPTIONS.md
```

## Deploy on Render

`render.yaml` defines two Docker web services. After the first deploy set `NEXT_PUBLIC_API_URL` on `verdict-web`
and `FRONTEND_ORIGIN` on `verdict-api` to each other's public URLs, then redeploy. The database is SQLite on the
instance's ephemeral disk and is reseeded on start, which is fine for a demo.

**Set your own tokens.** `render.yaml` does not ship default tokens. Set `API_TOKEN` on `verdict-api` and
`NEXT_PUBLIC_API_TOKEN` on `verdict-web` to the **same** long random string (for example `openssl rand -hex 24`), and set
`WEBHOOK_SIM_SECRET` to a different random string. `NEXT_PUBLIC_*` values are baked in at build time, so redeploy
`verdict-web` after changing it. The browser token is visible to anyone who opens the site, which is acceptable for a
judged demo but means you should not reuse it anywhere else.

**PayPal `invalid_client`?** Run `python scripts/check_paypal_credentials.py` from `backend/` and read
[docs/PAYPAL_CREDENTIALS.md](docs/PAYPAL_CREDENTIALS.md).

## License

MIT. See [LICENSE](LICENSE).
