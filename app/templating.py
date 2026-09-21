"""One Jinja2 environment, with autoescaping turned on explicitly.

`docs/architecture.md` §10 requires explicit autoescaping and forbids treating
user text as template source, so the environment is built here rather than
relying on a framework default, and every caller goes through it.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).parent / "templates"

env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(default_for_string=True, default=True),
    undefined=__import__("jinja2").StrictUndefined,
)


def render_card(card: dict) -> str:
    """Render one progress card. User text is data: it is never compiled."""
    return env.get_template("card_progress.html").render(card=card)


def render_page(**context: object) -> str:
    return env.get_template("index.html").render(**context)
