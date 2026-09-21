"""Formatting rules from docs/architecture.md §5 and docs/test_plan.md §3."""

import pytest

from app.domain.presentation import format_number, format_signed


@pytest.mark.parametrize(
    ("value", "expected"),
    # architecture.md §5 fixes two decimal places but not a rounding mode.
    # This project rounds half-up, so 1.005 formats as 1.01.
    [(78, "78"), (78.0, "78"), (78.50, "78.5"), (1.005, "1.01"), (0.129, "0.13"), (-0.0, "0")],
)
def test_format_number_trims_and_normalises(value, expected):
    assert format_number(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(13, "+13"), (-13, "-13"), (0, "0"), (0.004, "<+0.01"), (-0.004, "<-0.01")],
)
def test_format_signed_marks_tiny_nonzero_changes(value, expected):
    assert format_signed(value) == expected


def test_signed_zero_is_not_marked_as_tiny():
    assert format_signed(0.0) == "0"


def test_no_missing_or_non_finite_markers_leak():
    for text in (format_number(0), format_signed(0), format_signed(-0.004)):
        assert "None" not in text and "nan" not in text.lower() and "inf" not in text.lower()
