"""Whole-report export (docs/scope.md §6, "Whole report").

The report is assembled from what each card already rendered, so the tests
that matter are about order, completeness and refusing to produce a document
that looks finished but is not.
"""

import re

from playwright.sync_api import Page, expect


def read_text_file(path) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def add_progress(page: Page, title: str, summary: str) -> None:
    page.click('[data-add-card="progress"]')
    card = page.locator(".editor-card").last
    card.get_by_label("Title").fill(title)
    card.get_by_label("Summary").fill(summary)
    expect(card.locator(".card")).to_contain_text(title)


def add_metric(page: Page, title: str, current: str, previous: str = "") -> None:
    page.click('[data-add-card="metric"]')
    card = page.locator(".editor-card").last
    card.get_by_label("Metric name").fill(title)
    card.get_by_label("Current value").fill(current)
    if previous:
        card.get_by_label("Previous value").fill(previous)
    # Percentage on purpose: "percentage points" is only meaningful for a
    # percentage, and it is the wording the report is checked for.
    card.get_by_label("Unit", exact=True).select_option("percent")
    expect(card.locator(".card")).to_contain_text(title)


def two_cards(page: Page, base_url: str) -> None:
    page.goto(base_url)
    add_progress(page, "Payments migration", "Login refactor finished.")
    add_metric(page, "Onboarding completion", "79", "67")


def report_text(page: Page) -> str:
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.get_by_role("button", name="Copy report").click()
    expect(page.locator("#app-status")).to_contain_text(re.compile("report copied", re.I))
    return page.evaluate("navigator.clipboard.readText()")


# --- plain text -----------------------------------------------------------


def test_the_report_contains_every_card(page: Page, base_url: str):
    two_cards(page, base_url)
    text = report_text(page)
    assert "Payments migration" in text
    assert "Onboarding completion" in text
    # The computed comparison travels with it: the report is the rendered
    # content, not a dump of the form fields.
    assert "+12 percentage points" in text


def test_the_report_follows_the_order_on_screen(page: Page, base_url: str):
    two_cards(page, base_url)
    before = report_text(page)
    assert before.index("Payments migration") < before.index("Onboarding completion")

    page.locator(".editor-card").nth(1).get_by_role("button", name="Move up").click()
    expect(page.locator(".editor-card").first.locator(".card")).to_contain_text(
        "Onboarding completion"
    )

    after = report_text(page)
    assert after.index("Onboarding completion") < after.index("Payments migration")


def test_an_empty_report_is_refused_rather_than_exported(page: Page, base_url: str):
    page.goto(base_url)
    page.get_by_role("button", name="Copy report").click()
    expect(page.locator("#app-status")).to_contain_text(re.compile("no cards", re.I))


def test_an_invalid_card_blocks_the_export_and_is_named(page: Page, base_url: str):
    """A document that looks complete must never be missing a card."""
    two_cards(page, base_url)
    page.click('[data-add-card="progress"]')
    page.locator(".editor-card").last.get_by_label("Title").fill("Not filled in")

    page.get_by_role("button", name="Copy report").click()
    status = page.locator("#app-status")
    expect(status).to_contain_text(re.compile("could not|cannot", re.I))
    expect(status).to_contain_text("Not filled in")


def test_an_image_card_contributes_its_description(page: Page, base_url: str):
    page.goto(base_url)
    add_progress(page, "Payments migration", "Login refactor finished.")
    page.click('[data-add-card="image"]')
    card = page.locator(".editor-card").last
    card.get_by_label("Title").fill("Latency chart")
    card.get_by_label("Alternative text").fill("Median latency falling over six weeks")
    card.get_by_label("Caption").fill("Weeks 32 to 38")
    expect(card.locator(".card")).to_contain_text("Latency chart")

    text = report_text(page)
    assert "Latency chart" in text
    assert "Median latency falling over six weeks" in text


# --- HTML file ------------------------------------------------------------


def test_html_download_is_a_self_contained_document(page: Page, base_url: str):
    two_cards(page, base_url)

    with page.expect_download() as download:
        page.get_by_role("button", name="Download HTML").click()
    path = download.value.path()
    assert download.value.suggested_filename.endswith(".html")

    html = read_text_file(path)
    assert html.lstrip().startswith("<!doctype html")
    assert "Payments migration" in html
    assert "Onboarding completion" in html
    assert "+12 percentage points" in html
    # Self-contained: the card markup carries its own inline styles, so the
    # file must not depend on the application being reachable.
    assert "/static/css" not in html
    assert "<script" not in html.lower()


def test_html_keeps_the_order_and_escapes_user_text(page: Page, base_url: str):
    page.goto(base_url)
    add_progress(page, "First card", "<img src=x onerror=alert(1)>")
    add_progress(page, "Second card", "Plain.")

    with page.expect_download() as download:
        page.get_by_role("button", name="Download HTML").click()
    html = read_text_file(download.value.path())

    assert html.index("First card") < html.index("Second card")
    # Escaped text legitimately still contains the substring "onerror=alert(1)",
    # so asserting its absence would fail on correctly escaped output. What
    # matters is that it is text and not an element.
    assert "&lt;img" in html
    assert "<img" not in html


def test_html_export_is_refused_when_a_card_is_invalid(page: Page, base_url: str):
    two_cards(page, base_url)
    page.click('[data-add-card="metric"]')
    page.locator(".editor-card").last.get_by_label("Metric name").fill("No value yet")

    downloads = []
    page.on("download", lambda d: downloads.append(d))
    page.get_by_role("button", name="Download HTML").click()
    expect(page.locator("#app-status")).to_contain_text("No value yet")
    page.wait_for_timeout(1000)
    assert downloads == [], "a document was produced despite an invalid card"


# --- print / PDF ----------------------------------------------------------


def test_print_hides_the_editing_controls(page: Page, base_url: str):
    """PDF is the browser's own print. The stylesheet is what makes it a
    report rather than a screenshot of an editor."""
    two_cards(page, base_url)
    page.emulate_media(media="print")

    # Two toolbars now: adding cards, and sharing the report.
    for index in range(page.locator(".toolbar").count()):
        expect(page.locator(".toolbar").nth(index)).to_be_hidden()
    expect(page.locator(".editor-card__form").first).to_be_hidden()
    expect(page.locator(".editor-card__controls").first).to_be_hidden()
    expect(page.locator(".editor-card__share").first).to_be_hidden()
    # What remains is the rendered cards.
    expect(page.locator(".editor-card .card").first).to_be_visible()
