# Verdict: know which disputes to fight

Verdict is an AI agent for small online merchants that handles **PayPal payment disputes end to end**. When a
dispute arrives it gathers evidence, scores how winnable the case is, and decides to **FIGHT**, **REFUND** or
**ESCALATE** to the merchant. It acts only inside **hard guardrails enforced in code** (the model cannot override
them), and it logs every decision with its reasoning.

Built as a prototype for the PayPal AI Hackathon. It is **not** an official PayPal product.

> **Honesty note.** By default PayPal calls are served by a clearly labeled **mock adapter** and disputes come from a
> built-in **simulator** that posts signed PayPal-style webhooks to this app's own endpoint. With `PAYPAL_MODE=sandbox`
> the real PayPal sandbox is used where it supports the call. See [docs/PAYPAL_CALLS.md](docs/PAYPAL_CALLS.md) for
> exactly which calls are real and which are simulated.

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
* **Guard**: precedence is *expired > missing evidence > above approval threshold ($250) > refund above auto-refund cap ($100) > low confidence > conflicting evidence (blocks FIGHT)*. Guardrails can only **downgrade**, never upgrade. 472 unit tests pin this, including an exhaustive "never upgrade" property check.
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
cd backend && python -m pytest -q     # 472 tests: guardrails, policy, scoring, webhooks, idempotency, cases A/B/C x3
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

## License

MIT. See [LICENSE](LICENSE).
