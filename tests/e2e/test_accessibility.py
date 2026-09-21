"""axe-core scans of the states listed in docs/test_plan.md §9."""

from playwright.sync_api import Page, expect

from tests.e2e.axe_helper import assert_clean


def test_empty_editor(page: Page, base_url: str):
    page.goto(base_url)
    expect(page.locator("#empty-state")).to_be_visible()
    assert_clean(page, "empty editor")


def test_populated_cards(page: Page, base_url: str):
    page.goto(base_url)
    for kind in ("progress", "metric", "image"):
        page.click(f'[data-add-card="{kind}"]')
    page.locator(".editor-card").nth(0).locator('input[name="title"]').fill("Payments migration")
    page.locator(".editor-card").nth(0).locator('textarea[name="summary"]').fill("Moving on.")
    page.wait_for_timeout(500)
    assert_clean(page, "populated cards")


def test_validation_errors(page: Page, base_url: str):
    page.goto(base_url)
    page.click('[data-add-card="progress"]')
    page.fill('input[name="title"]', "x" * 121)
    expect(page.locator(".field__error").first).to_be_visible()
    assert_clean(page, "validation errors")


def test_confirmation_dialog(page: Page, base_url: str):
    page.goto(base_url)
    page.click('[data-add-card="progress"]')
    page.get_by_role("button", name="Delete").first.click()
    expect(page.locator("dialog")).to_be_visible()
    assert_clean(page, "confirmation dialog")


def test_mobile_width(page: Page, base_url: str):
    page.set_viewport_size({"width": 360, "height": 780})
    page.goto(base_url)
    page.click('[data-add-card="metric"]')
    page.wait_for_timeout(400)
    assert_clean(page, "360px layout")
    # Core operations must survive a narrow viewport (test_plan §9).
    expect(page.locator('[data-add-card="metric"]')).to_be_visible()
    expect(page.locator(".editor-card__controls button").first).to_be_visible()
