from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Assessment, Dispute

AUTO_STATUSES = {"REFUNDED", "EVIDENCE_SUBMITTED"}
HANDLED_STATUSES = AUTO_STATUSES | {"RESOLVED", "EXPIRED"}


def impact_metrics(db: Session) -> dict:
    disputes = db.scalars(select(Dispute)).all()
    win = {a.dispute_id: a.win_likelihood for a in db.scalars(select(Assessment)).all()}
    fought = [d for d in disputes if d.status == "EVIDENCE_SUBMITTED"]
    # Modeled: expected recovery = disputed amount x the agent's own win likelihood. Not a measured outcome.
    recovered = sum((d.amount * Decimal(str(round(win.get(d.id, 0.0), 4))) for d in fought), Decimal("0")).quantize(Decimal("0.01"))
    handled = [d for d in disputes if d.status in HANDLED_STATUSES]
    minutes = settings.modeled_minutes_per_case
    return {
        "disputes_handled": len(handled),
        "disputes_total": len(disputes),
        "auto_resolved": sum(d.status in AUTO_STATUSES for d in disputes),
        "escalated": sum(d.status == "AWAITING_APPROVAL" for d in disputes),
        "refunds_issued": sum(d.status == "REFUNDED" for d in disputes),
        "evidence_submitted": len(fought),
        "modeled_revenue_recovered": str(recovered),
        "modeled_hours_saved": round(len(handled) * minutes / 60, 1),
        "assumptions": {
            "label": "MODELED, not measured",
            "minutes_per_manual_case": minutes,
            "revenue_recovered": "Sum over submitted evidence packets of disputed amount x the agent's win likelihood.",
            "time_saved": "Handled disputes x minutes per manual case.",
        },
    }
