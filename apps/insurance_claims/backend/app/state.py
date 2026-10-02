"""Session state: phase, memory with provenance, verification, counters and the event trace."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Phase(str, Enum):
    VERIFY_ID = "VERIFY_ID"
    RESOLVE_INTENT = "RESOLVE_INTENT"
    PROCESS_CASE = "PROCESS_CASE"
    POST_PROCESS = "POST_PROCESS"
    HUMAN_TRANSFER = "HUMAN_TRANSFER"
    ENDED = "ENDED"


PII_FIELDS = ("name", "dob", "phone", "email", "id_last4")


class Slot(BaseModel):
    """A remembered value plus the turn it was heard on (provenance)."""

    value: Any
    turn: int


class Memory(BaseModel):
    # Identity fields as stated by the caller (about the policyholder).
    pii: dict[str, Slot] = Field(default_factory=dict)
    policy_number: Slot | None = None
    caller_role: Slot | None = None  # "policyholder" | "representative"
    representative_name: Slot | None = None
    representative_relationship: Slot | None = None
    # Later-phase information captured whenever the caller says it.
    intent: Slot | None = None
    case_hints: dict[str, Slot] = Field(default_factory=dict)  # case_id, case_type, status, month, year
    followup_topics: list[Slot] = Field(default_factory=list)
    caller_notes: list[Slot] = Field(default_factory=list)  # free-text useful facts the caller shared
    lacks_document: Slot | None = None
    cannot_obtain_alternatives: Slot | None = None

    def set(self, key: str, value: Any, turn: int) -> bool:
        current = getattr(self, key)
        if value is None or (current is not None and current.value == value):
            return False
        setattr(self, key, Slot(value=value, turn=turn))
        return True

    def hint_text(self) -> str:
        parts = []
        h = self.case_hints
        if "status" in h:
            parts.append(h["status"].value)
        if "case_type" in h:
            parts.append(h["case_type"].value)
        parts.append("claim")
        if "month" in h:
            parts.append("from " + MONTHS[int(h["month"].value) - 1])
        if "case_id" in h:
            parts.append(f"({h['case_id'].value})")
        return " ".join(parts) if len(parts) > 1 else ""


MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


class Verification(BaseModel):
    status: Literal["unverified", "verified", "locked"] = "unverified"
    party_id: str | None = None
    matched_fields: list[str] = Field(default_factory=list)
    failed_attempts: int = 0
    failed_signatures: list[str] = Field(default_factory=list)


class Consent(BaseModel):
    required: bool = False
    scenario: str = "default"
    status: Literal["not_required", "pending", "approved", "timeout"] = "not_required"
    polls: int = 0


class Counters(BaseModel):
    off_topic_streak: int = 0
    off_topic_total: int = 0
    verification_refusals: int = 0
    frustration_streak: int = 0
    injection_attempts: int = 0


class EmailState(BaseModel):
    offered: bool = False
    choice: Literal["send", "skip"] | None = None
    sent_to: str | None = None
    preview: dict[str, Any] | None = None


class Event(BaseModel):
    turn: int
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    turn: int
    citations: list[dict[str, Any]] = Field(default_factory=list)


class SessionState(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    phase: Phase = Phase.VERIFY_ID
    turn: int = 0
    memory: Memory = Field(default_factory=Memory)
    verification: Verification = Field(default_factory=Verification)
    consent: Consent = Field(default_factory=Consent)
    selected_case_id: str | None = None
    candidate_case_ids: list[str] = Field(default_factory=list)
    discussed_topics: list[str] = Field(default_factory=list)
    alternatives_offered: bool = False
    pending_offer: Literal["human_transfer", "email"] | None = None
    counters: Counters = Field(default_factory=Counters)
    email: EmailState = Field(default_factory=EmailState)
    transfer_reason: str | None = None
    transcript: list[Message] = Field(default_factory=list)
    trace: list[Event] = Field(default_factory=list)

    def log(self, type_: str, **data: Any) -> Event:
        event = Event(turn=self.turn, type=type_, data=data)
        self.trace.append(event)
        return event

    def set_phase(self, phase: Phase, reason: str) -> None:
        if phase != self.phase:
            self.log("phase_change", from_phase=self.phase.value, to_phase=phase.value, reason=reason)
            self.phase = phase

    @property
    def verified(self) -> bool:
        return self.verification.status == "verified" and (
            not self.consent.required or self.consent.status == "approved"
        )
