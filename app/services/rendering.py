"""Render one card into the three outputs the API returns."""

from app.schemas.cards import ImageCard, MetricCard, ProgressCard
from app.services.plain_text import to_plain_text
from app.services.presentation_model import build_view
from app.templating import env


def render_card(card: ProgressCard | MetricCard | ImageCard) -> tuple[str, str, str | None]:
    """Return (preview_html, plain_text, rich_html).

    Image cards have no rich HTML: the file stays in the browser, so an email
    body would reference an image the recipient cannot load (architecture §6).
    """
    view = build_view(card)
    preview_html = env.get_template("preview/card.html").render(view=view)
    plain_text = to_plain_text(view)
    rich_html = (
        None
        if isinstance(card, ImageCard)
        else env.get_template("email/card.html").render(view=view)
    )
    return preview_html, plain_text, rich_html
