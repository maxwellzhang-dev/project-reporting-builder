"""Metric comparison: one pure function, no rounding, no formatting.

Rules come from docs/architecture.md §5. Rounding and unit labels belong to
`app.domain.presentation` so preview, email and plain text cannot drift apart.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class MetricError(ValueError):
    """Raised for non-finite inputs or non-finite results."""


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class Comparison:
    absolute: float
    # None when the baseline is zero: the ratio is undefined, not zero.
    relative_percent: float | None
    direction: Direction


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise MetricError(f"{name} must be a real number")
    if not math.isfinite(value):
        raise MetricError(f"{name} must be finite")
    return float(value)


def compare(current: float, previous: float | None) -> Comparison | None:
    """Compare a metric against its baseline, or return None when there is none."""
    current = _finite(current, "current")
    if previous is None:
        return None
    previous = _finite(previous, "previous")

    absolute = current - previous
    if not math.isfinite(absolute):
        raise MetricError("absolute change is not finite")

    if absolute > 0:
        direction = Direction.UP
    elif absolute < 0:
        direction = Direction.DOWN
    else:
        direction = Direction.UNCHANGED

    relative: float | None = None
    if previous != 0:
        # A negative baseline uses its magnitude, so direction stays meaningful.
        relative = absolute / abs(previous) * 100
        if not math.isfinite(relative):
            raise MetricError("relative change is not finite")

    return Comparison(absolute=absolute, relative_percent=relative, direction=direction)
