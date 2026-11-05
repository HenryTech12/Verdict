# Submission package

## Tagline
Know which disputes to fight.

## Description (paste into Devpost)

**What it does.** Verdict is an AI agent for small online merchants that handles PayPal payment disputes end to end.
When a dispute webhook arrives it gathers evidence (order record, tracking and delivery proof, address match,
customer messages, merchant policy), scores how winnable the case is, and decides whether to **fight**, **refund**
or **escalate** to the merchant. It acts only inside hard guardrails that are enforced in code, and it logs every
decision with its inputs, reasoning and rule.

**Why it matters.** Small merchants have no finance team. Disputes have strict deadlines and need specific
evidence, so merchants miss deadlines, lose cases they could have won, or waste effort on cases they cannot win.

**The part we care about most.** Verdict is willing to *not* fight. In our conflict case the tracking says
"delivered" but to a different address than the order. Verdict detects the conflict, concludes the case is weak,
and refunds automatically (under the merchant's cap) instead of submitting evidence that would lose.

**How it is built.** A deterministic checklist score is the backbone of every assessment; the LLM reads qualitative
evidence (messages) and can only nudge the score within a bounded range. A guardrails engine written in code, not in
a prompt, has final authority: it can downgrade an action but never upgrade one. Above the approval threshold,
above the refund cap, with low confidence, with conflicting evidence, with missing records, or past the deadline, a
human decides or nothing happens. Actions are idempotent so a retry cannot refund twice.

**Dashboard.** An AG Grid table with live updates (server-sent events), deadline countdowns, win-likelihood bars,
decision badges, an expandable reasoning row with the evidence checklist and audit timeline, an approval queue, a
merchant settings page, evidence packet download, and a modeled impact panel.

## Honest scope statement
This is our own prototype, not an official PayPal product. By default PayPal calls use a clearly labeled mock
adapter and disputes come from a built-in simulator that posts signed PayPal-style webhooks to our own endpoint.
Sandbox mode implements the real webhook-verification, provide-evidence and refund calls; see
[PAYPAL_CALLS.md](PAYPAL_CALLS.md) for exactly what is real and what is simulated. Impact numbers are modeled from
stated assumptions, not measured. All data is seeded demo data; no real customer data is used.

## Tools and models used
* **PayPal**: webhooks and signature verification, Customer Disputes API (provide evidence), Payments API (refund), sandbox only.
* **LLM**: Groq-hosted `openai/gpt-oss-120b` through a thin provider interface for the qualitative evidence assessment, rationale and packet narrative; a deterministic offline stand-in is the default so judges need no API key.
* **Backend**: FastAPI, SQLAlchemy, SQLite, server-sent events, httpx.
* **Frontend**: Next.js, React, TypeScript, AG Grid Community, AG Studio (analytics pages), Tailwind.
* **Quality**: pytest (472 tests), Vitest, Playwright, ESLint, TypeScript.
* **Prizes targeted**: Best Use of PayPal + AI, Best Use of AG Grid, Most Impactful, main prizes (add Render if hosted there). Check the Official Rules on stacking prizes.

## Checklist before Nov 12, 2026, 9:00pm GMT+1
- [ ] Final name check (Verdict / Rebut / Parley / Counsel): domain, GitHub, trademark
- [ ] Public repo with the LICENSE visible in the About section
- [ ] README setup steps verified from a clean clone (target under 10 minutes)
- [ ] Hosted demo URL (Render) and recorded fallback video
- [ ] `python scripts/sandbox_spike.py` run with real credentials; matrix pasted into PAYPAL_CALLS.md
- [ ] Demo video under 3 minutes on YouTube, public, no copyrighted music or third-party trademarks
- [ ] Submission form completed with buffer (aim to submit by Nov 11)
- [ ] Rotate any API keys that were ever shared or zipped
