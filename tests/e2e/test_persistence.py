"""Local draft recovery, from docs/test_plan.md §6.

Each test gets its own browser context, and recovery is checked by reloading
that same context rather than opening a new one.
"""

import base64

from playwright.sync_api import Page, expect

# 1x1 PNG, small enough to keep the test fast.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def add(page: Page, kind: str) -> None:
    page.click(f'[data-add-card="{kind}"]')


def test_saved_appears_only_after_the_write_succeeds(page: Page, base_url: str):
    page.goto(base_url)
    add(page, "progress")
    expect(page.locator("#save-state")).to_have_text("Saved locally", timeout=5000)
    assert page.locator("#save-state").get_attribute("data-state") == "saved"


def test_text_and_order_recover_after_reload(page: Page, base_url: str):
    page.goto(base_url)
    add(page, "progress")
    add(page, "metric")
    page.locator(".editor-card").nth(0).locator('input[name="title"]').fill("First card")
    page.locator(".editor-card").nth(1).locator('input[name="title"]').fill("Second card")
    page.locator(".editor-card").nth(1).get_by_role("button", name="Move up").click()
    expect(page.locator("#save-state")).to_have_text("Saved locally", timeout=5000)

    page.reload()
    expect(page.locator(".editor-card")).to_have_count(2)
    expect(page.locator(".editor-card").nth(0).locator('input[name="title"]')).to_have_value(
        "Second card"
    )
    expect(page.locator(".editor-card").nth(1).locator('input[name="title"]')).to_have_value(
        "First card"
    )
    expect(page.locator("#app-status")).to_contain_text("Draft restored")


def test_incomplete_drafts_are_saved_and_restored(page: Page, base_url: str):
    page.goto(base_url)
    add(page, "metric")
    page.fill('input[name="current"]', "42")  # title deliberately left blank
    expect(page.locator("#save-state")).to_have_text("Saved locally", timeout=5000)

    page.reload()
    expect(page.locator('input[name="current"]')).to_have_value("42")
    expect(page.locator('input[name="title"]')).to_have_value("")


def test_restored_cards_render_through_the_normal_flow(page: Page, base_url: str):
    page.goto(base_url)
    add(page, "metric")
    page.fill('input[name="title"]', "Completion rate")
    page.fill('input[name="current"]', "78")
    page.fill('input[name="previous"]', "65")
    page.select_option('select[name="unit"]', "percent")
    expect(page.locator("#save-state")).to_have_text("Saved locally", timeout=5000)

    page.reload()
    expect(page.locator(".card__value")).to_have_text("78%", timeout=5000)
    expect(page.locator(".card__comparisons")).to_contain_text("+13 percentage points")


def test_image_blobs_recover_with_a_fresh_object_url(page: Page, base_url: str):
    page.goto(base_url)
    add(page, "image")
    page.fill('input[name="title"]', "Burndown")
    page.fill('input[name="alt_text"]', "Burndown chart trending down")
    page.set_input_files(
        '.editor-card input[type="file"]',
        {
            "name": "chart.png",
            "mimeType": "image/png",
            "buffer": TINY_PNG,
        },
    )
    expect(page.locator(".card__image")).to_be_visible(timeout=5000)
    expect(page.locator("#save-state")).to_have_text("Saved locally", timeout=5000)

    page.reload()
    image = page.locator(".card__image")
    expect(image).to_be_visible(timeout=5000)
    assert image.get_attribute("src").startswith("blob:")
    assert image.get_attribute("alt") == "Burndown chart trending down"


def test_deleting_a_card_removes_its_stored_image(page: Page, base_url: str):
    page.goto(base_url)
    add(page, "image")
    page.fill('input[name="alt_text"]', "Chart to be deleted")
    page.set_input_files(
        '.editor-card input[type="file"]',
        {
            "name": "chart.png",
            "mimeType": "image/png",
            "buffer": TINY_PNG,
        },
    )
    expect(page.locator("#save-state")).to_have_text("Saved locally", timeout=5000)

    page.get_by_role("button", name="Delete").first.click()
    page.locator("#confirm-delete").get_by_role("button", name="Delete").click()
    # "Saved locally" is already on screen from the previous save, so waiting for
    # that text would pass before this write lands. Poll the store itself.
    page.wait_for_function(
        """async () => {
            const db = await new Promise((resolve) => {
                const r = indexedDB.open('project-reporting-builder');
                r.onsuccess = () => resolve(r.result);
            });
            const [cards, keys] = await Promise.all([
                new Promise((resolve) => {
                    const q = db.transaction('reports').objectStore('reports').get('current');
                    q.onsuccess = () => resolve(q.result?.cards?.length ?? 0);
                }),
                new Promise((resolve) => {
                    const q = db.transaction('assets').objectStore('assets').getAllKeys();
                    q.onsuccess = () => resolve(q.result);
                }),
            ]);
            return cards === 0 && keys.length === 0;
        }""",
        timeout=5000,
    )


def test_clear_local_data_removes_the_draft_and_autosave_cannot_recreate_it(
    page: Page, base_url: str
):
    page.goto(base_url)
    add(page, "progress")
    page.fill('input[name="title"]', "Temporary")
    expect(page.locator("#save-state")).to_have_text("Saved locally", timeout=5000)

    page.click("#clear-local-data")
    expect(page.locator(".editor-card")).to_have_count(0)
    expect(page.locator("#app-status")).to_contain_text("cleared")

    page.wait_for_timeout(1200)  # outlast any pending autosave
    page.reload()
    expect(page.locator(".editor-card")).to_have_count(0)
    expect(page.locator("#empty-state")).to_be_visible()


def test_rendered_html_is_not_persisted(page: Page, base_url: str):
    """architecture §8: never store rendered HTML or Object URLs."""
    page.goto(base_url)
    add(page, "progress")
    page.fill('input[name="title"]', "No HTML please")
    expect(page.locator("#save-state")).to_have_text("Saved locally", timeout=5000)

    stored = page.evaluate(
        """async () => {
            const db = await new Promise((resolve) => {
                const r = indexedDB.open('project-reporting-builder');
                r.onsuccess = () => resolve(r.result);
            });
            return await new Promise((resolve) => {
                const request = db.transaction('reports').objectStore('reports').get('current');
                request.onsuccess = () => resolve(JSON.stringify(request.result));
            });
        }"""
    )
    assert "<article" not in stored and "blob:" not in stored
    assert "objectUrl" not in stored
