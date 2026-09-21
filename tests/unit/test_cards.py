"""Card validation, from docs/test_plan.md §3 and the limits in architecture §4."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.cards import ImageCard, MetricCard, ProgressCard, Status, Unit, parse_card

ID = str(uuid.uuid4())


def progress(**overrides) -> dict:
    return {
        "id": ID,
        "type": "progress",
        "title": "Payments migration",
        "status": "in_progress",
        "summary": "Twelve of eighteen accounts moved.",
    } | overrides


def metric(**overrides) -> dict:
    return {
        "id": ID,
        "type": "metric",
        "title": "Completion rate",
        "current": 78,
        "previous": 65,
        "unit": "percent",
    } | overrides


def image(**overrides) -> dict:
    return {
        "id": ID,
        "type": "image",
        "title": "Burndown",
        "alt_text": "Burndown chart trending down",
    } | overrides


def test_each_type_parses_into_its_own_model():
    assert isinstance(parse_card(progress()), ProgressCard)
    assert isinstance(parse_card(metric()), MetricCard)
    assert isinstance(parse_card(image()), ImageCard)


def test_unknown_type_is_rejected():
    with pytest.raises(ValidationError):
        parse_card(progress(type="chart"))


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        parse_card(progress(colour="red"))


def test_id_must_be_a_uuid():
    with pytest.raises(ValidationError):
        parse_card(progress(id="not-a-uuid"))


def test_blank_required_fields_are_rejected_after_trimming():
    for field in ("title", "summary"):
        with pytest.raises(ValidationError):
            parse_card(progress(**{field: "   "}))


def test_title_length_boundary():
    assert parse_card(progress(title="x" * 120)).title == "x" * 120
    with pytest.raises(ValidationError):
        parse_card(progress(title="x" * 121))


def test_progress_list_limits():
    assert len(parse_card(progress(completed=["ok"] * 8)).completed) == 8
    with pytest.raises(ValidationError):
        parse_card(progress(completed=["ok"] * 9))
    with pytest.raises(ValidationError):
        parse_card(progress(completed=["x" * 301]))


def test_status_must_be_known():
    assert parse_card(progress()).status is Status.IN_PROGRESS
    with pytest.raises(ValidationError):
        parse_card(progress(status="nearly_done"))


def test_custom_unit_requires_a_label():
    with pytest.raises(ValidationError):
        parse_card(metric(unit="custom", unit_label=""))
    card = parse_card(metric(unit="custom", unit_label="stories"))
    assert card.unit is Unit.CUSTOM and card.unit_label == "stories"


def test_unit_label_is_rejected_beyond_its_limit():
    with pytest.raises(ValidationError):
        parse_card(metric(unit="custom", unit_label="x" * 17))


@pytest.mark.parametrize("value", ["78", True, float("nan"), float("inf")])
def test_metric_values_reject_strings_booleans_and_non_finite(value):
    with pytest.raises(ValidationError):
        parse_card(metric(current=value))


def test_missing_previous_differs_from_zero():
    assert parse_card(metric(previous=None)).previous is None
    assert parse_card(metric(previous=0)).previous == 0


def test_image_card_requires_alt_text_and_rejects_files():
    with pytest.raises(ValidationError):
        parse_card(image(alt_text="  "))
    for forbidden in (
        {"src": "data:image/png;base64,AAAA"},
        {"url": "https://x/y.png"},
        {"file": "blob:http://localhost/abc"},
    ):
        with pytest.raises(ValidationError):
            parse_card(image(**forbidden))


def test_alt_text_and_caption_limits():
    parse_card(image(alt_text="a" * 300, caption="c" * 1000))
    with pytest.raises(ValidationError):
        parse_card(image(alt_text="a" * 301))
    with pytest.raises(ValidationError):
        parse_card(image(caption="c" * 1001))


def test_union_rejects_a_card_without_a_type():
    with pytest.raises(ValidationError):
        parse_card({"id": ID, "title": "No type", "summary": "x"})
