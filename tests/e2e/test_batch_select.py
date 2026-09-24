"""Selecting cards and acting on the selection: copy, download, print, delete.

With nothing selected the report actions cover every card, as before; with a
selection they cover exactly the selected cards, in report order.
"""

import re

import pytest
from playwright.sync_api import Page, expect


def three_cards(page: Page, base_url: str):
    page.goto(base_url)
    for title in ("Alpha", "Bravo", "Charlie"):
        page.click('[data-add-card="progress"]')
        card = page.locator(".editor-card").last
        card.locator('input[name="title"]').fill(title)
        card.locator('textarea[name="summary"]').fill(f"{title} summary.")
    for title in ("Alpha", "Bravo", "Charlie"):
        expect(page.locator(".editor-card .card__title", has_text=title)).to_be_visible()
    return page.locator(".editor-card")


def select(cards, *indexes):
    for index in indexes:
        cards.nth(index).get_by_role("checkbox", name="Select card").check()


def test_the_bar_says_what_the_actions_will_cover(page: Page, base_url: str):
    cards = three_cards(page, base_url)
    scope = page.locator("#report-scope")
    expect(scope).to_have_text("Select cards to export")
    expect(page.get_by_role("button", name="Copy selected")).to_be_disabled()
    expect(page.get_by_role("button", name="Delete selected")).to_be_hidden()

    select(cards, 0, 2)
    expect(scope).to_have_text("2 of 3 selected")
    expect(page.get_by_role("button", name="Copy selected")).to_be_visible()
    expect(page.get_by_role("button", name="Download selected")).to_be_visible()
    expect(page.get_by_role("button", name="Print selected")).to_be_visible()
    expect(cards.nth(0)).to_have_class(re.compile("is-selected"))
    expect(cards.nth(1)).not_to_have_class(re.compile("is-selected"))

    page.get_by_role("button", name="Clear selection").click()
    expect(scope).to_have_text("Select cards to export")
    expect(page.get_by_role("button", name="Copy selected")).to_be_disabled()
    expect(cards.nth(0).get_by_role("checkbox", name="Select card")).not_to_be_checked()


def test_select_all_then_clear(page: Page, base_url: str):
    cards = three_cards(page, base_url)
    page.get_by_role("button", name="Select all").click()
    expect(page.locator("#report-scope")).to_have_text("3 of 3 selected")
    for index in range(3):
        expect(cards.nth(index).get_by_role("checkbox", name="Select card")).to_be_checked()
    expect(page.get_by_role("button", name="Select all")).to_be_hidden()


@pytest.mark.browser_context_args(permissions=["clipboard-read", "clipboard-write"])
def test_copy_covers_only_the_selection_in_report_order(page: Page, base_url: str):
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    cards = three_cards(page, base_url)
    select(cards, 2, 0)  # ticked out of order on purpose
    page.get_by_role("button", name="Copy selected").click()
    expect(page.locator("#app-status")).to_have_text("2 cards copied")
    text = page.evaluate("navigator.clipboard.readText()")
    assert "Alpha" in text and "Charlie" in text and "Bravo" not in text
    assert text.index("Alpha") < text.index("Charlie")


def test_download_covers_only_the_selection(page: Page, base_url: str):
    cards = three_cards(page, base_url)
    select(cards, 1)
    with page.expect_download() as download:
        page.get_by_role("button", name="Download selected").click()
    with open(download.value.path(), encoding="utf-8") as file:
        html = file.read()
    assert "Bravo" in html and "Alpha" not in html and "Charlie" not in html


def test_print_leaves_out_the_unselected_cards_and_restores_them(page: Page, base_url: str):
    cards = three_cards(page, base_url)
    select(cards, 0)
    # Record which cards were excluded at the moment print was called.
    page.evaluate(
        """window.print = () => { window.__excluded = [...document.querySelectorAll('.editor-card')]
            .map(node => node.classList.contains('is-print-excluded')); }"""
    )
    page.get_by_role("button", name="Print selected").click()
    assert page.evaluate("window.__excluded") == [False, True, True]
    page.wait_for_timeout(100)
    assert page.locator(".editor-card.is-print-excluded").count() == 0


def test_delete_selected_asks_first_then_removes_exactly_those(page: Page, base_url: str):
    cards = three_cards(page, base_url)
    select(cards, 0, 2)
    page.get_by_role("button", name="Delete selected").click()
    dialog = page.locator("#confirm-delete")
    expect(dialog).to_contain_text("Delete the 2 selected cards?")
    dialog.get_by_role("button", name="Cancel").click()
    expect(cards).to_have_count(3)
    expect(page.locator("#report-scope")).to_have_text("2 of 3 selected")

    page.get_by_role("button", name="Delete selected").click()
    dialog.get_by_role("button", name="Delete").click()
    expect(cards).to_have_count(1)
    expect(cards.first.locator(".card__title")).to_have_text("Bravo")
    expect(page.locator("#app-status")).to_have_text("2 cards deleted")
    # Nothing left selected: the deleted cards took their selection with them.
    expect(page.locator("#report-scope")).to_have_text("Select cards to export")


def test_selection_is_not_saved(page: Page, base_url: str):
    cards = three_cards(page, base_url)
    select(cards, 1)
    expect(page.locator("#save-state")).to_have_text("Saved locally", timeout=5000)
    page.reload()
    expect(page.locator(".editor-card")).to_have_count(3)
    expect(page.locator("#report-scope")).to_have_text("Select cards to export")
