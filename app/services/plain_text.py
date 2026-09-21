"""Plain text serialised from the presentation model, never by stripping HTML."""

from app.services.presentation_model import CardView


def to_plain_text(view: CardView) -> str:
    lines: list[str] = [view.title]

    if view.status_label:
        lines.append(f"Status: {view.status_label}")
    if view.summary:
        lines += ["", view.summary]
    if view.value:
        lines.append(view.value)
    lines += view.comparisons
    if view.alt_text:
        lines.append(f"Image description: {view.alt_text}")
    if view.caption:
        lines.append(view.caption)
    if view.note:
        lines += ["", view.note]

    for section in view.sections:
        lines += ["", section.heading]
        lines += [f"- {item}" for item in section.items]

    return "\n".join(lines).strip() + "\n"
