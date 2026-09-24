"""An image in the notes panel, from docs/test_plan.md §7.

A status report, slide or dashboard is often all someone has, so the notes
panel takes an image as well as text. These tests are mostly about limits:
nothing is sent before Generate, what is sent is a downscaled copy, and a
draft read from an image cannot become a card until its figures have been
checked.
"""

import json

from playwright.sync_api import Page, expect

from tests.e2e.axe_helper import assert_clean
from tests.e2e.test_image_describe import image_bytes

ROUTE = "**/api/ai/extract-progress"


def open_panel(page: Page, base_url: str):
    page.goto(base_url)
    page.get_by_role("button", name="Paste notes, draft with AI").click()
    return page.locator("#ai-review")


def attach(page: Page, width: int = 400, height: int = 200):
    page.locator("#ai-image").set_input_files(
        {"name": "status.png", "mimeType": "image/png", "buffer": image_bytes(page, width, height)}
    )
    expect(page.locator("#ai-image-preview")).to_be_visible()


def test_a_screenshot_can_be_attached_and_removed(page: Page, base_url: str):
    open_panel(page, base_url)
    attach(page)
    assert page.locator("#ai-image-thumb").get_attribute("src").startswith("blob:")

    page.get_by_role("button", name="Remove image").click()
    expect(page.locator("#ai-image-preview")).to_be_hidden()
    expect(page.locator("#ai-image")).to_be_focused()


def test_a_screenshot_pasted_into_the_notes_is_attached(page: Page, base_url: str):
    open_panel(page, base_url)
    page.locator("#ai-source").fill("Sprint 25 notes.")
    page.evaluate(
        """async () => {
            const blob = await new Promise((done) => {
                const canvas = document.createElement("canvas");
                canvas.width = 40; canvas.height = 20;
                canvas.toBlob(done, "image/png");
            });
            const data = new DataTransfer();
            data.items.add(new File([blob], "paste.png", { type: "image/png" }));
            document.getElementById("ai-source").dispatchEvent(
                new ClipboardEvent("paste",
                    { clipboardData: data, bubbles: true, cancelable: true }),
            );
        }"""
    )
    expect(page.locator("#ai-image-preview")).to_be_visible()
    expect(page.locator("#ai-source")).to_have_value("Sprint 25 notes.")


def test_attaching_sends_nothing_until_generate(page: Page, base_url: str):
    open_panel(page, base_url)
    sent = []
    page.on("request", lambda request: sent.append(request) if "extract" in request.url else None)
    attach(page)
    page.wait_for_timeout(300)
    assert sent == []


def test_a_screenshot_alone_is_enough_and_is_sent_downscaled(page: Page, base_url: str):
    open_panel(page, base_url)
    attach(page, width=2400, height=1200)
    with page.expect_request(ROUTE) as captured:
        page.get_by_role("button", name="Generate draft").click()
    body = json.loads(captured.value.post_data)
    assert body["source_text"] == ""
    assert body["image_data_url"].startswith("data:image/jpeg;base64,")
    size = page.evaluate(
        "async (u) => { const i = new Image(); i.src = u; await i.decode();"
        " return [i.naturalWidth, i.naturalHeight]; }",
        body["image_data_url"],
    )
    assert size == [1024, 512]
    expect(page.locator("#ai-draft-title")).to_have_value("Draft from image")


def test_nothing_at_all_is_refused_in_the_page(page: Page, base_url: str):
    open_panel(page, base_url)
    page.get_by_role("button", name="Generate draft").click()
    expect(page.locator("#ai-error")).to_contain_text("notes or add an image")


def test_figures_from_a_screenshot_must_be_checked_before_create(page: Page, base_url: str):
    panel = open_panel(page, base_url)
    attach(page)
    page.get_by_role("button", name="Generate draft").click()
    expect(page.locator("#ai-draft")).to_be_visible()

    figures = panel.locator("#ai-numbers li")
    expect(figures).to_have_text(["79%"])
    page.select_option("#ai-draft-status", "in_progress")
    create = panel.get_by_role("button", name="Create card")
    expect(create).to_be_disabled()  # a status alone is not enough here

    check = panel.get_by_label("I checked every number against the image")
    check.check()
    expect(create).to_be_enabled()

    # A changed figure has not been checked.
    page.locator("#ai-draft-summary").fill("Onboarding completion reached 97%.")
    expect(figures).to_have_text(["97%", "79%"])
    expect(check).not_to_be_checked()
    expect(create).to_be_disabled()

    check.check()
    create.click()
    expect(page.locator(".editor-card")).to_have_count(1)


def test_a_draft_from_notes_alone_needs_no_figure_check(page: Page, base_url: str):
    panel = open_panel(page, base_url)
    page.locator("#ai-source").fill("Twelve of 18 accounts moved; 3 remain blocked.")
    page.get_by_role("button", name="Generate draft").click()
    expect(page.locator("#ai-draft")).to_be_visible()
    expect(panel.locator("#ai-numbers-block")).to_be_hidden()
    page.select_option("#ai-draft-status", "in_progress")
    expect(panel.get_by_role("button", name="Create card")).to_be_enabled()


def test_closing_the_panel_drops_the_screenshot(page: Page, base_url: str):
    open_panel(page, base_url)
    attach(page)
    page.get_by_role("button", name="Cancel").click()
    page.get_by_role("button", name="Paste notes, draft with AI").click()
    expect(page.locator("#ai-image-preview")).to_be_hidden()
    assert page.locator("#ai-image-thumb").get_attribute("src") is None


def test_the_panel_with_a_screenshot_passes_an_accessibility_scan(page: Page, base_url: str):
    open_panel(page, base_url)
    attach(page)
    page.wait_for_timeout(300)
    assert_clean(page, "notes panel, image attached")
    page.get_by_role("button", name="Generate draft").click()
    expect(page.locator("#ai-numbers-block")).to_be_visible()
    page.wait_for_timeout(300)
    assert_clean(page, "notes panel, figures to check")
