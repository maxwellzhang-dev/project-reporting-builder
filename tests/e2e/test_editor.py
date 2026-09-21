"""Editing and card management, from docs/test_plan.md §5."""

import re

from playwright.sync_api import Page, expect


def add(page: Page, kind: str) -> None:
    page.click(f'[data-add-card="{kind}"]')


def test_add_each_card_type_and_see_a_live_preview(page: Page, base_url: str):
    page.goto(base_url)
    expect(page.locator("#empty-state")).to_be_visible()

    add(page, "progress")
    expect(page.locator("#empty-state")).to_be_hidden()
    page.fill('input[name="title"]', "Payments migration")
    page.fill('textarea[name="summary"]', "Twelve of eighteen accounts moved.")
    expect(page.locator(".preview__body .card__title")).to_have_text("Payments migration")

    add(page, "metric")
    metric = page.locator(".editor-card").nth(1)
    metric.locator('input[name="title"]').fill("Completion rate")
    metric.locator('input[name="current"]').fill("78")
    metric.locator('input[name="previous"]').fill("65")
    metric.locator('select[name="unit"]').select_option("percent")
    expect(metric.locator(".card__value")).to_have_text("78%")
    expect(metric.locator(".card__comparisons")).to_contain_text("+13 percentage points")
    expect(metric.locator(".card__comparisons")).to_contain_text("+20% relative change")


def test_validation_errors_are_shown_against_their_field(page: Page, base_url: str):
    page.goto(base_url)
    add(page, "progress")
    page.fill('input[name="title"]', "x" * 121)
    error = page.locator('.field:has(input[name="title"]) .field__error')
    expect(error).to_be_visible()
    expect(page.locator('input[name="title"]')).to_have_attribute("aria-invalid", "true")


def test_move_and_delete_with_confirmation(page: Page, base_url: str):
    page.goto(base_url)
    add(page, "progress")
    add(page, "metric")
    page.locator(".editor-card").nth(0).locator('input[name="title"]').fill("First")
    page.locator(".editor-card").nth(1).locator('input[name="title"]').fill("Second")

    page.locator(".editor-card").nth(1).get_by_role("button", name="Move up").click()
    expect(page.locator(".editor-card").nth(0).locator('input[name="title"]')).to_have_value(
        "Second"
    )

    page.locator(".editor-card").nth(0).get_by_role("button", name="Delete").click()
    expect(page.locator("#confirm-delete")).to_be_visible()
    page.get_by_role("button", name="Cancel").click()
    expect(page.locator(".editor-card")).to_have_count(2)

    page.locator(".editor-card").nth(0).get_by_role("button", name="Delete").click()
    page.locator("#confirm-delete").get_by_role("button", name="Delete").click()
    expect(page.locator(".editor-card")).to_have_count(1)
    expect(page.locator(".editor-card").nth(0).locator('input[name="title"]')).to_have_value(
        "First"
    )
    expect(page.locator("#app-status")).to_contain_text("deleted")


def test_card_count_and_limit(page: Page, base_url: str):
    page.goto(base_url)
    expect(page.locator("#card-count")).to_have_text("0 of 20 cards")
    for _ in range(20):
        add(page, "metric")
    expect(page.locator("#card-count")).to_have_text("20 of 20 cards")
    expect(page.locator('[data-add-card="metric"]')).to_be_disabled()


def test_a_deleted_card_does_not_reappear_when_its_request_lands(page: Page, base_url: str):
    """A slow render for a deleted card must not resurrect it (test_plan §5)."""
    page.goto(base_url)
    add(page, "progress")
    page.route(
        "**/api/cards/render",
        lambda route: (page.wait_for_timeout(400), route.continue_()),
    )
    page.fill('input[name="title"]', "Doomed")
    page.get_by_role("button", name="Delete").click()
    page.locator("#confirm-delete").get_by_role("button", name="Delete").click()
    page.wait_for_timeout(900)
    expect(page.locator(".editor-card")).to_have_count(0)
    expect(page.locator("#empty-state")).to_be_visible()


def test_focus_moves_somewhere_sensible_after_deletion(page: Page, base_url: str):
    page.goto(base_url)
    add(page, "progress")
    add(page, "metric")
    page.locator(".editor-card").nth(0).get_by_role("button", name="Delete").click()
    page.locator("#confirm-delete").get_by_role("button", name="Delete").click()
    expect(page.locator(".editor-card")).to_have_count(1)
    # Focus lands on a real control inside the card that took its place.
    assert page.evaluate("document.activeElement?.closest('.editor-card') !== null")
    assert page.evaluate("document.activeElement?.disabled") in (False, None)


def test_status_is_not_conveyed_by_colour_alone(page: Page, base_url: str):
    page.goto(base_url)
    add(page, "progress")
    page.fill('input[name="title"]', "Colour check")
    page.fill('textarea[name="summary"]', "Status must be readable as text.")
    expect(page.locator(".card__status")).to_contain_text(re.compile("In Progress"))


def test_keyboard_only_user_can_add_a_card(page: Page, base_url: str):
    page.goto(base_url)
    page.keyboard.press("Tab")  # skip link
    page.keyboard.press("Tab")  # first toolbar button
    page.keyboard.press("Enter")
    expect(page.locator(".editor-card")).to_have_count(1)
    assert page.evaluate("document.activeElement?.name") == "title"
