"""User text must reach the page as data, never as markup or template source."""

from app.services.presentation_model import CardView, Section
from app.templating import env


def render_card(card: dict) -> str:
    """Render the preview template the API serves, from a hostile card."""
    view = CardView(
        kind="progress",
        title=card["title"],
        status_label=card["status_label"],
        status_value=card["status_value"],
        summary=card["summary"],
        sections=[
            Section(heading, items)
            for heading, items in (
                ("Completed", card["completed"]),
                ("Next steps", card["next_steps"]),
                ("Risks", card["risks"]),
            )
            if items
        ],
    )
    return env.get_template("preview/card.html").render(view=view)


HOSTILE = {
    "title": "<script>alert('xss')</script>",
    "status_value": "in_progress",
    "status_label": "In Progress",
    "summary": 'Budget cut by 5% & scope "reduced"',
    "completed": ["{{ 7 * 7 }}"],
    "next_steps": ["<img src=x onerror=alert(1)>"],
    "risks": [],
}


def test_script_tags_are_escaped():
    html = render_card(HOSTILE)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_template_syntax_in_user_text_is_not_evaluated():
    html = render_card(HOSTILE)
    assert "49" not in html
    assert "{{ 7 * 7 }}" in html


def test_attribute_payloads_are_inert():
    html = render_card(HOSTILE)
    # The text survives verbatim; what matters is that it is no longer a tag.
    assert "<img" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_ampersands_and_quotes_survive_as_text():
    html = render_card(HOSTILE)
    assert "&amp;" in html and "&#34;reduced&#34;" in html


def test_empty_optional_sections_are_omitted():
    assert "Risks" not in render_card(HOSTILE)
