"""
schemas.py — Pydantic models matching the schema.md contract exactly.
"""
from __future__ import annotations
from typing import Any, Literal, Optional
from datetime import date
from pydantic import BaseModel, Field, field_validator, model_validator

TERMINAL_STATES = Literal[
    "booked", "rescheduled", "cancelled", "escalated", "refused", "abandoned"
]
ESCALATION_REASONS = Literal[
    "clinical_urgent", "medical_advice", "not_authorised",
    "ambiguous_patient", "out_of_scope"
]


class AgentRequest(BaseModel):
    """POST /agent/run — inbound payload."""
    conversation_id: str = Field(min_length=1, max_length=200)
    today: str           # YYYY-MM-DD — NEVER use system clock
    turns: list[str] = Field(max_length=50)

    @field_validator("today")
    @classmethod
    def valid_today(cls, value):
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("today must use YYYY-MM-DD")
        return value

    @field_validator("turns")
    @classmethod
    def bounded_turns(cls, value):
        if any(len(turn) > 10000 for turn in value):
            raise ValueError("Each caller turn must be at most 10000 characters")
        return value


class ToolCall(BaseModel):
    """A single tool invocation logged during the run."""
    name: str
    arguments: dict[str, Any]
    result: Optional[Any] = None


class Metrics(BaseModel):
    turns: int = Field(ge=0)
    tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)


class AgentResponse(BaseModel):
    """POST /agent/run — outbound payload per schema.md."""
    conversation_id: str
    tool_calls: list[ToolCall]
    terminal_state: TERMINAL_STATES
    escalation_reason: Optional[ESCALATION_REASONS] = None
    patient_id: Optional[str] = None
    appointment_id: Optional[str] = None
    reply: str
    metrics: Metrics

    @model_validator(mode="after")
    def escalation_reason_matches_state(self):
        if (self.terminal_state == "escalated") != (self.escalation_reason is not None):
            raise ValueError("escalation_reason is required exactly when terminal_state is escalated")
        if self.terminal_state in {"booked", "rescheduled", "cancelled"} and not self.appointment_id:
            raise ValueError("Successful mutations require an appointment_id")
        return self
