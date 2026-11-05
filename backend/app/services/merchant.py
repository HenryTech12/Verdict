from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Merchant
from app.schemas import SettingsSchema

DEFAULT_POLICY = "Orders ship within 2 business days with tracking. Delivery is confirmed by carrier scan."


def get_merchant(db: Session) -> Merchant:
    merchant = db.scalar(select(Merchant).order_by(Merchant.id))
    if not merchant:
        merchant = Merchant(name="Verdict Demo Merchant", settings_json={})
        db.add(merchant)
        db.flush()
    return merchant


def settings_for(db: Session) -> SettingsSchema:
    merchant = db.scalar(select(Merchant).order_by(Merchant.id))
    stored = merchant.settings_json if merchant else {}
    return SettingsSchema(
        auto_refund_cap=Decimal(str(stored.get("auto_refund_cap", settings.auto_refund_cap))),
        approval_threshold=Decimal(str(stored.get("approval_threshold", settings.approval_threshold))),
        fight_min_win_likelihood=float(stored.get("fight_min_win_likelihood", settings.fight_min_win_likelihood)),
        refund_max_win_likelihood=float(stored.get("refund_max_win_likelihood", settings.refund_max_win_likelihood)),
        min_confidence=float(stored.get("min_confidence", settings.min_confidence)),
        shipping_policy_text=str(stored.get("shipping_policy_text", DEFAULT_POLICY)),
    )


def save_settings(db: Session, payload: SettingsSchema) -> SettingsSchema:
    merchant = get_merchant(db)
    merchant.settings_json = {
        "auto_refund_cap": str(payload.auto_refund_cap),
        "approval_threshold": str(payload.approval_threshold),
        "fight_min_win_likelihood": payload.fight_min_win_likelihood,
        "refund_max_win_likelihood": payload.refund_max_win_likelihood,
        "min_confidence": payload.min_confidence,
        "shipping_policy_text": payload.shipping_policy_text,
    }
    db.commit()
    return settings_for(db)


def thresholds(s: SettingsSchema) -> dict[str, object]:
    return {
        "fight_min_win_likelihood": s.fight_min_win_likelihood,
        "refund_max_win_likelihood": s.refund_max_win_likelihood,
        "min_confidence": s.min_confidence,
        "approval_threshold": s.approval_threshold,
        "auto_refund_cap": s.auto_refund_cap,
    }
