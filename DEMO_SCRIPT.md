# Demo video script (under 3 minutes)

Record at 1080p. Use `STAGE_DELAY_MS=400` in `.env` so the audit timeline visibly fills in. No music, no third-party
logos (the PRD requires no copyrighted music or third-party trademarks). Say "simulated" out loud where it applies.

| Time | Screen | Say |
|---|---|---|
| 0:00 | Dashboard, impact panel | "Small merchants have no finance team. Disputes have hard deadlines, so they miss them, lose winnable cases, or waste time on unwinnable ones. Verdict is an agent that knows which disputes to fight." |
| 0:15 | Point at PAYPAL: MOCK / LLM badges | "This is a prototype. Disputes come from a simulator that posts signed PayPal-style webhooks to our own endpoint. Mock versus real sandbox calls are labeled everywhere." |
| 0:25 | Click **Case A** | "Case A: item not received, $80. Verdict gathers the order, tracking, address match, delivery photo and messages, scores the case, decides FIGHT, and submits the evidence packet on its own." Expand the row: checklist, rule fired, audit timeline. |
| 0:55 | Click **Case B** | "Case B is the moment I care about. Tracking says delivered, but to a different address than the order. Verdict detects the conflict, drops the win likelihood, and chooses not to fight. It refunds $90 automatically because that is under my $100 cap." Expand the row: "Agent chose not to fight", conflict banner, rule fired. |
| 1:30 | Click **Case C** | "Case C: $480, strong evidence. The policy says FIGHT, but a guardrail in code says anything above $250 needs a human. The model cannot override that." Show the GUARDRAIL line and the Awaiting approval chip. |
| 1:55 | Approve in the row | "I approve and the packet is submitted. Every step is in the audit log with its inputs, outputs and rule." |
| 2:10 | Click **Case E**, then Settings | "A case with under 24 hours left is flagged urgent and sorted first. Limits are mine to set: change the refund cap and the next case respects it." |
| 2:30 | Impact panel, README test section | "Impact is modeled, not measured, and the assumptions are shown. Guardrails have 482 unit tests, including a check that no input can make the agent take a riskier action than the model proposed." |
| 2:50 | Title card | "Verdict. Know which disputes to fight." |
