from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="Demo Merchant")
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"))
    customer_name: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    items_json: Mapped[list] = mapped_column(JSON, default=list)
    ship_address: Mapped[str] = mapped_column(String(300))
    policy_accepted: Mapped[bool] = mapped_column(default=True)
    paypal_capture_id: Mapped[str] = mapped_column(String(80))


class Shipment(Base):
    __tablename__ = "shipments"
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), primary_key=True)
    carrier: Mapped[str] = mapped_column(String(50), default="SIMULATED CARRIER")
    tracking: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_address: Mapped[str] = mapped_column(String(300))
    proof_url: Mapped[str | None] = mapped_column(String(300), nullable=True)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    sender: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Dispute(Base):
    __tablename__ = "disputes"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    paypal_dispute_id: Mapped[str] = mapped_column(String(80), unique=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    reason: Mapped[str] = mapped_column(String(60), default="ITEM_NOT_RECEIVED")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(30), default="NEW")
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    simulated: Mapped[bool] = mapped_column(default=True)
    case: Mapped[str] = mapped_column(String(1), default="A")
    __table_args__ = (UniqueConstraint("paypal_dispute_id"),)


class Assessment(Base):
    __tablename__ = "assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    dispute_id: Mapped[str] = mapped_column(ForeignKey("disputes.id"), unique=True)
    evidence_json: Mapped[list] = mapped_column(JSON, default=list)
    conflicts_json: Mapped[list] = mapped_column(JSON, default=list)
    checklist_score: Mapped[float] = mapped_column(default=0)
    win_likelihood: Mapped[float] = mapped_column(default=0)
    confidence: Mapped[float] = mapped_column(default=0)
    recommended: Mapped[str] = mapped_column(String(20))
    rationale: Mapped[str] = mapped_column(Text)
    packet_draft: Mapped[str] = mapped_column(Text)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    dispute_id: Mapped[str] = mapped_column(ForeignKey("disputes.id"), unique=True)
    policy_decision: Mapped[str] = mapped_column(String(20))
    guardrail_rule: Mapped[str | None] = mapped_column(String(120), nullable=True)
    final_action: Mapped[str] = mapped_column(String(30))


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    dispute_id: Mapped[str] = mapped_column(ForeignKey("disputes.id"), unique=True)
    requested_action: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    recommendation_summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    dispute_id: Mapped[str] = mapped_column(ForeignKey("disputes.id"))
    step: Mapped[str] = mapped_column(String(30))
    summary: Mapped[str] = mapped_column(Text)
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    simulated: Mapped[bool] = mapped_column(default=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
