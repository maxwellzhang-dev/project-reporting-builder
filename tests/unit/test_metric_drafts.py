"""Validation of proposed metric cards (docs/scope.md §5).

The rule these protect is narrow and the whole feature rests on it: a proposal
copies figures the text states, and an absent baseline stays absent.
"""

import pytest
from pydantic import ValidationError

from app.schemas.ai import DRAFT_METRICS_MAX, ExtractResponse, MetricDraft


def draft(**overrides):
    base = {"title": "Onboarding completion", "current": 79.0, "unit": "percent"}
    return MetricDraft.model_validate(base | overrides)


def test_a_stated_baseline_is_kept():
    metric = draft(previous=67.0)
    assert metric.current == 79.0
    assert metric.previous == 67.0


def test_an_absent_baseline_is_none_not_zero():
    """Zero is a real baseline and must never stand in for "not stated"."""
    metric = draft()
    assert metric.previous is None


def test_an_explicit_null_baseline_is_accepted():
    assert draft(previous=None).previous is None


def test_zero_survives_as_a_baseline():
    assert draft(previous=0).previous == 0.0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, False])
def test_non_finite_and_boolean_values_are_rejected(value):
    with pytest.raises(ValidationError):
        draft(current=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_the_same_applies_to_the_baseline(value):
    with pytest.raises(ValidationError):
        draft(previous=value)


def test_a_blank_title_is_rejected():
    with pytest.raises(ValidationError):
        draft(title="   ")


def test_unknown_units_are_rejected():
    with pytest.raises(ValidationError):
        draft(unit="furlongs")


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        MetricDraft.model_validate({"title": "T", "current": 1, "unit": "number", "difference": 12})


def test_a_response_without_metrics_is_valid():
    """Proposing nothing is an ordinary answer, not a failure."""
    response = ExtractResponse.model_validate(
        {
            "draft": {
                "title": "T",
                "summary": "S",
                "completed_items": [],
                "next_steps": [],
                "risks": [],
            }
        }
    )
    assert response.metrics == []


def test_too_many_metrics_are_rejected():
    many = [
        {"title": f"m{i}", "current": i, "unit": "number"} for i in range(DRAFT_METRICS_MAX + 1)
    ]
    with pytest.raises(ValidationError):
        ExtractResponse.model_validate(
            {
                "draft": {
                    "title": "T",
                    "summary": "S",
                    "completed_items": [],
                    "next_steps": [],
                    "risks": [],
                },
                "metrics": many,
            }
        )


def test_a_label_is_kept_only_where_it_means_something():
    """The live model returns "%" beside unit "percent" and "users" beside
    "number". Rendering ignores both, but they would appear the moment the
    unit was switched to custom, so they are dropped on the way in."""
    assert draft(unit="percent", unit_label="%").unit_label == ""
    assert draft(unit="number", unit_label="users").unit_label == ""
    assert draft(unit="custom", unit_label="ms").unit_label == "ms"
