from typing import Protocol

from pydantic import BaseModel, Field


class EvidenceOutput(BaseModel):
    type: str
    present: bool
    strength: float = Field(ge=0, le=1)
    note: str


class AssessmentOutput(BaseModel):
    evidence_items: list[EvidenceOutput]
    conflicts: list[str]
    win_likelihood: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    recommended: str
    rationale: str
    packet_draft: str
    token_usage: dict[str, int] | None = None


class LLMProvider(Protocol):
    async def assess(self, case_context: dict[str, object]) -> AssessmentOutput:
        ...
