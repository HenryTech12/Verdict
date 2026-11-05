# Decision policy and guardrails

Defaults are configurable per merchant in Settings. Treat them as starting points to tune on the seeded cases.

## Policy (maps assessment to a decision, records the rule that fired)

| Rule fired | Condition | Decision |
|---|---|---|
| `FIGHT_THRESHOLD` | win likelihood >= 0.60 and confidence >= 0.70 | FIGHT |
| `REFUND_THRESHOLD` | win likelihood < 0.35 and confidence >= 0.70 | REFUND |
| `LOW_CONFIDENCE_DEFAULT` | confidence < 0.70 | ESCALATE |
| `UNCERTAIN_BAND_DEFAULT` | 0.35 <= win likelihood < 0.60 | ESCALATE |

Win likelihood = deterministic checklist score, nudged by the LLM by at most +/-0.15, then capped at 0.25 when the
code finds a hard conflict (for example tracking delivered to an address that differs from the order).

## Resolving "conflict means escalate" versus Case B

A **conflict that lowers the win likelihood into the refund band** is what makes Verdict choose REFUND in Case B:
fighting a visibly weak case is the wrong call, and refunding under the cap is safe. A **conflict on a case the
policy wants to FIGHT** (for example a customer message disputing the delivery location) is escalated by the
`CONFLICTING_EVIDENCE` guardrail instead.

## Guardrails (code, run after the model and before any action)

Evaluated in this order; the first that applies wins. They can only downgrade an action.

| Order | Rule | Default | Effect |
|---|---|---|---|
| 1 | `DEADLINE_EXPIRED` | deadline passed | No action. Logged and the merchant is notified. |
| 2 | `MISSING_EVIDENCE` | no order or shipment record for the transaction | ESCALATE |
| 3 | `AMOUNT_ABOVE_APPROVAL_THRESHOLD` | amount > $250 | ESCALATE (any action needs a human above this) |
| 4 | `REFUND_ABOVE_AUTO_REFUND_CAP` | refund amount > $100 | ESCALATE |
| 5 | `LOW_CONFIDENCE` | confidence < 0.70 | ESCALATE |
| 6 | `CONFLICTING_EVIDENCE` | FIGHT with any conflict | ESCALATE |

Also: under 24h left flags the approval request **URGENT** and sorts it first; the model cannot change thresholds
or skip a rule; model or API failures retry at most twice and then ESCALATE with the error logged; actions are
idempotent per `(dispute, action)`.

Tests: `backend/tests/test_guardrails.py` pins every boundary, the precedence order, custom limits, and an
exhaustive property test that no input combination upgrades an action.
