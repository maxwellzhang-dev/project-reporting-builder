"""The one shape preview, email and plain text all render from.

Building this once is what keeps the three outputs saying the same thing
(docs/architecture.md §5, §10).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.metrics import compare
from app.domain.presentation import format_number, format_signed
from app.schemas.cards import ImageCard, MetricCard, ProgressCard, Unit


@dataclass(frozen=True)
class Section:
    heading: str
    items: list[str]


@dataclass(frozen=True)
class CardView:
    kind: str
    title: str
    status_label: str | None = None
    status_value: str | None = None
    summary: str | None = None
    sections: list[Section] = field(default_factory=list)
    value: str | None = None
    comparisons: list[str] = field(default_factory=list)
    note: str | None = None
    alt_text: str | None = None
    caption: str | None = None


def _unit_suffix(card: MetricCard) -> str:
    if card.unit is Unit.PERCENT:
        return "%"
    if card.unit is Unit.CUSTOM:
        return f" {card.unit_label}"
    return ""


def _progress_view(card: ProgressCard) -> CardView:
    sections = [
        Section(heading, items)
        for heading, items in (
            ("Completed", card.completed),
            ("Next steps", card.next_steps),
            ("Risks", card.risks),
        )
        if items  # Empty optional sections are omitted (scope §4).
    ]
    return CardView(
        kind="progress",
        title=card.title,
        status_label=card.status_label,
        status_value=card.status.value,
        summary=card.summary,
        sections=sections,
    )


def _metric_view(card: MetricCard) -> CardView:
    suffix = _unit_suffix(card)
    comparisons: list[str] = []
    result = compare(card.current, card.previous)
    if result is not None:
        # For percentages the absolute difference is in points, not percent.
        unit_word = "percentage points" if card.unit is Unit.PERCENT else suffix.strip() or None
        absolute = format_signed(result.absolute)
        comparisons.append(f"{absolute} {unit_word}".strip() if unit_word else absolute)
        if result.relative_percent is not None:
            comparisons.append(f"{format_signed(result.relative_percent)}% relative change")
    return CardView(
        kind="metric",
        title=card.title,
        value=f"{format_number(card.current)}{suffix}",
        comparisons=comparisons,
        note=card.note or None,
    )


def _image_view(card: ImageCard) -> CardView:
    return CardView(
        kind="image",
        title=card.title,
        alt_text=card.alt_text,
        caption=card.caption or None,
    )


def build_view(card: ProgressCard | MetricCard | ImageCard) -> CardView:
    if isinstance(card, ProgressCard):
        return _progress_view(card)
    if isinstance(card, MetricCard):
        return _metric_view(card)
    return _image_view(card)
