"""Rendering keeps preview, email and plain-text card content aligned."""

from uuid import UUID

from app.schemas.cards import ImageCard, MetricCard, ProgressCard, Status, Unit
from app.services.rendering import render_card

CARD_ID = UUID("12345678-1234-5678-1234-567812345678")


def test_metric_renders_the_same_comparisons_in_every_available_format():
    card = MetricCard(
        id=CARD_ID,
        type="metric",
        title="Completion rate",
        current=78,
        previous=65,
        unit=Unit.PERCENT,
        note="Measured at the weekly checkpoint.",
    )

    preview_html, plain_text, rich_html = render_card(card)

    for output in (preview_html, plain_text, rich_html):
        assert output is not None
        assert "Completion rate" in output
        assert "78%" in output
        assert "+13 percentage points" in output
        assert "+20% relative change" in output
        assert "Measured at the weekly checkpoint." in output


def test_progress_omits_empty_sections_from_every_format():
    card = ProgressCard(
        id=CARD_ID,
        type="progress",
        title="Payments migration",
        status=Status.IN_PROGRESS,
        summary="Twelve accounts moved.",
        completed=["Dual-write enabled"],
        next_steps=[],
        risks=[],
    )

    preview_html, plain_text, rich_html = render_card(card)

    for output in (preview_html, plain_text, rich_html):
        assert output is not None
        assert "Completed" in output
        assert "Dual-write enabled" in output
        assert "Next steps" not in output
        assert "Risks" not in output


def test_image_card_is_preview_and_plain_text_only():
    card = ImageCard(
        id=CARD_ID,
        type="image",
        title="Burndown",
        alt_text="Burndown chart trending down",
        caption="Week 38",
    )

    preview_html, plain_text, rich_html = render_card(card)

    assert rich_html is None
    assert 'data-image-slot="true"' in preview_html
    assert "Burndown chart trending down" in preview_html
    assert plain_text == "Burndown\nImage description: Burndown chart trending down\nWeek 38\n"
