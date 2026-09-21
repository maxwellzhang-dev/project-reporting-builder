"""Metric calculation, written from the table in docs/test_plan.md §3.

Calculation never rounds; formatting is a separate concern (architecture §5).
"""

import math

import pytest

from app.domain.metrics import Direction, MetricError, compare


def test_missing_previous_gives_no_comparison():
    assert compare(120, None) is None


@pytest.mark.parametrize(
    ("current", "previous", "absolute", "relative", "direction"),
    [
        (120, 100, 20, 20.0, Direction.UP),
        (80, 100, -20, -20.0, Direction.DOWN),
        (100, 100, 0, 0.0, Direction.UNCHANGED),
        (0, 100, -100, -100.0, Direction.DOWN),
        (-80, -100, 20, 20.0, Direction.UP),
        (-120, -100, -20, -20.0, Direction.DOWN),
    ],
)
def test_comparison_table(current, previous, absolute, relative, direction):
    result = compare(current, previous)
    assert result.absolute == pytest.approx(absolute)
    assert result.relative_percent == pytest.approx(relative)
    assert result.direction is direction


@pytest.mark.parametrize(
    ("current", "previous", "absolute", "direction"),
    [(10, 0, 10, Direction.UP), (0, 0, 0, Direction.UNCHANGED)],
)
def test_zero_baseline_keeps_absolute_change_but_drops_relative(
    current, previous, absolute, direction
):
    result = compare(current, previous)
    assert result.absolute == pytest.approx(absolute)
    assert result.relative_percent is None
    assert result.direction is direction


def test_fractional_values():
    result = compare(0.3, 0.2)
    assert result.absolute == pytest.approx(0.1)
    assert result.relative_percent == pytest.approx(50.0)


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_non_finite_inputs_are_rejected(value):
    with pytest.raises(MetricError):
        compare(value, 1)
    with pytest.raises(MetricError):
        compare(1, value)


def test_non_finite_result_is_rejected():
    with pytest.raises(MetricError):
        compare(1e308, -1e308)


def test_percentage_metrics_use_the_documented_scale():
    """65 to 78 is +13 percentage points and +20% relative (architecture §5)."""
    result = compare(78, 65)
    assert result.absolute == pytest.approx(13)
    assert result.relative_percent == pytest.approx(20.0)
