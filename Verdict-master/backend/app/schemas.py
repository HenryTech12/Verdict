from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DecisionName = Literal["FIGHT", "REFUND", "ESCALATE"]


class ErrorBody(BaseModel):
    error: dict[str, Any]


class Health(BaseModel):
    status: str
    paypal_mode: str
    llm_provider: str
    version: str


class EvidenceItem(BaseModel):
    type: str
    present: bool
    strength: float = Field(ge=0, le=1)
    note: str


class DisputeListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    paypal_dispute_id: str
    customer_name: str
    amount: Decimal
    currency: str
    reason: str
    status: str
    deadline: datetime
    win_likelihood: float | None = None
    confidence: float | None = None
    decision: str | None = None
    policy_decision: str | None = None
    guardrail_rule: str | None = None
    urgent: bool = False
    simulated: bool
    created_at: datetime


class DisputeListResponse(BaseModel):
    items: list[DisputeListItem]
    total: int
    page: int
    page_size: int


class ApprovalActionBody(BaseModel):
    note: str | None = Field(default=None, max_length=1000)
    action: Literal["FIGHT", "REFUND"] | None = None


class SimulationResponse(BaseModel):
    dispute_id: str
    case: str
    simulated: bool


class ApprovalItem(BaseModel):
    id: int
    dispute_id: str
    requested_action: str
    recommendation_summary: str
    amount: Decimal | None = None
    deadline: datetime | None = None
    status: str
    created_at: datetime


class SettingsSchema(BaseModel):
    auto_refund_cap: Decimal = Field(gt=0)
    approval_threshold: Decimal = Field(gt=0)
    fight_min_win_likelihood: float = Field(ge=0, le=1)
    refund_max_win_likelihood: float = Field(ge=0, le=1)
    min_confidence: float = Field(ge=0, le=1)
    shipping_policy_text: str

    @model_validator(mode="after")
    def valid_thresholds(self) -> "SettingsSchema":
        if self.fight_min_win_likelihood <= self.refund_max_win_likelihood:
            raise ValueError("fight_min_win_likelihood must be greater than refund_max_win_likelihood")
        return self
