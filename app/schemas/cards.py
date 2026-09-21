"""Card models: a discriminated union on `type`, rejecting anything unexpected.

Limits are the table in docs/architecture.md §4. The API accepts image metadata
only — never files, base64 payloads, remote URLs or Object URLs (§4, scope §7).
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

TITLE_MAX = 120
SUMMARY_MAX = 2_000
LIST_MAX_ITEMS = 8
LIST_ITEM_MAX = 300
NOTE_MAX = 500
UNIT_LABEL_MAX = 16
CAPTION_MAX = 1_000
ALT_TEXT_MAX = 300


class Status(str, Enum):
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    CLEARED_TO_START = "cleared_to_start"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    CANCELLED = "cancelled"


STATUS_LABELS: dict[Status, str] = {
    Status.PROPOSED: "Proposed",
    Status.UNDER_REVIEW: "Under Review",
    Status.CLEARED_TO_START: "Cleared to Start",
    Status.IN_PROGRESS: "In Progress",
    Status.COMPLETED: "Completed",
    Status.ON_HOLD: "On Hold",
    Status.CANCELLED: "Cancelled",
}


class Unit(str, Enum):
    NUMBER = "number"
    PERCENT = "percent"
    CUSTOM = "custom"


TrimmedText = Annotated[str, Field(min_length=1)]


class _CardBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID
    title: TrimmedText = Field(max_length=TITLE_MAX)


def _clean_list(items: list[str]) -> list[str]:
    cleaned = [item.strip() for item in items]
    if any(not item for item in cleaned):
        raise ValueError("list items cannot be blank")
    return cleaned


ProgressList = Annotated[
    list[Annotated[str, Field(max_length=LIST_ITEM_MAX)]],
    Field(default_factory=list, max_length=LIST_MAX_ITEMS),
]


class ProgressCard(_CardBase):
    type: Literal["progress"]
    status: Status
    summary: TrimmedText = Field(max_length=SUMMARY_MAX)
    completed: ProgressList
    next_steps: ProgressList
    risks: ProgressList

    @field_validator("completed", "next_steps", "risks")
    @classmethod
    def _no_blank_items(cls, items: list[str]) -> list[str]:
        return _clean_list(items)

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]


class MetricCard(_CardBase):
    type: Literal["metric"]
    current: float
    previous: float | None = None
    unit: Unit
    unit_label: str = Field(default="", max_length=UNIT_LABEL_MAX)
    note: str = Field(default="", max_length=NOTE_MAX)

    @field_validator("current", "previous", mode="before")
    @classmethod
    def _real_finite_numbers(cls, value: Any) -> Any:
        if value is None:
            return value
        # A boolean is an int in Python; a numeric string is not a number at all.
        if isinstance(value, bool | str):
            raise ValueError("must be a number, not a string or boolean")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("must be finite")
        return value

    @model_validator(mode="after")
    def _custom_unit_needs_a_label(self) -> MetricCard:
        if self.unit is Unit.CUSTOM and not self.unit_label.strip():
            raise ValueError("a custom unit needs a unit_label")
        return self


class ImageCard(_CardBase):
    type: Literal["image"]
    alt_text: TrimmedText = Field(max_length=ALT_TEXT_MAX)
    caption: str = Field(default="", max_length=CAPTION_MAX)


Card = Annotated[ProgressCard | MetricCard | ImageCard, Field(discriminator="type")]

_card_adapter: TypeAdapter[Card] = TypeAdapter(Card)


def parse_card(payload: Any) -> ProgressCard | MetricCard | ImageCard:
    """Validate an untrusted payload into exactly one card model."""
    return _card_adapter.validate_python(payload)
