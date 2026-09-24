"""Describing an image with AI, from docs/test_plan.md §7.

The image leaves the browser only here, so most of these tests are about what
does not happen: nothing is sent before the person presses Send, nothing
reaches the card before "Use this text", and what is sent is a downscaled
copy rather than the original file.
"""

import base64
import json

from playwright.sync_api import Page, expect

from tests.e2e.axe_helper import assert_clean

ROUTE = "**/api/ai/describe-image"


def image_bytes(page: Page, width: int, height: int) -> bytes:
    """A real PNG of the given size, drawn by the browser."""
    data_url = page.evaluate(
        """([w, h]) => {
            const canvas = document.createElement("canvas");
            canvas.width = w; canvas.height = h;
            const context = canvas.getContext("2d");
            context.fillStyle = "#4f46e5"; context.fillRect(0, 0, w, h);
            context.fillStyle = "#ffffff"; context.fillRect(w / 4, h / 4, w / 2, h / 2);
            return canvas.toDataURL("image/png");
        }""",
        [width, height],
    )
    return base64.b64decode(data_url.split(",", 1)[1])


def image_card(page: Page, base_url: str, width: int = 200, height: int = 100):
    page.goto(base_url)
    page.click('[data-add-card="image"]')
    card = page.locator(".editor-card").first
    card.locator('input[name="title"]').fill("Sign-ups")
    card.locator('input[type="file"]').set_input_files(
        {"name": "chart.png", "mimeType": "image/png", "buffer": image_bytes(page, width, height)}
    )
    # Not the preview image: alternative text is required, so an image card
    # without it previews as "review the highlighted fields". What matters
    # here is that the image was accepted.
    expect(card.get_by_role("button", name="Describe with AI")).to_be_enabled(timeout=5000)
    return card


def watch_requests(page: Page) -> list:
    sent = []
    page.on(
        "request", lambda request: sent.append(request) if "describe-image" in request.url else None
    )
    return sent


def test_the_button_waits_for_an_image(page: Page, base_url: str):
    page.goto(base_url)
    page.click('[data-add-card="image"]')
    button = page.get_by_role("button", name="Describe with AI")
    expect(button).to_be_disabled()
    page.locator('input[type="file"]').set_input_files(
        {"name": "chart.png", "mimeType": "image/png", "buffer": image_bytes(page, 20, 20)}
    )
    expect(button).to_be_enabled()


def test_opening_and_cancelling_send_nothing(page: Page, base_url: str):
    card = image_card(page, base_url)
    sent = watch_requests(page)

    card.get_by_role("button", name="Describe with AI").click()
    panel = page.locator("#image-ai")
    expect(panel).to_be_visible()
    # The consent step shows the image that would go.
    assert panel.locator("#image-ai-thumb").get_attribute("src").startswith("blob:")
    expect(panel).to_contain_text("Azure OpenAI")

    panel.get_by_role("button", name="Cancel").click()
    expect(panel).to_be_hidden()
    card.get_by_role("button", name="Describe with AI").click()
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()

    page.wait_for_timeout(300)
    assert sent == []


def test_a_downscaled_jpeg_is_sent_not_the_original(page: Page, base_url: str):
    card = image_card(page, base_url, width=2000, height=1000)
    card.get_by_role("button", name="Describe with AI").click()

    with page.expect_request(ROUTE) as captured:
        page.get_by_role("button", name="Send image and draft").click()
    body = json.loads(captured.value.post_data)
    assert list(body) == ["image_data_url"]
    url = body["image_data_url"]
    assert url.startswith("data:image/jpeg;base64,")

    size = page.evaluate(
        "async (u) => { const i = new Image(); i.src = u; await i.decode();"
        " return [i.naturalWidth, i.naturalHeight]; }",
        url,
    )
    assert size == [1024, 512]


def test_the_draft_reaches_the_card_only_through_use(page: Page, base_url: str):
    card = image_card(page, base_url)
    alt = card.locator('input[name="alt_text"]')
    caption = card.locator('[name="caption"]')
    card.get_by_role("button", name="Describe with AI").click()
    page.get_by_role("button", name="Send image and draft").click()

    panel = page.locator("#image-ai")
    expect(panel.locator("#image-ai-alt")).to_have_value(
        "Bar chart of weekly sign-ups, highest in week 4."
    )
    expect(panel.locator("#image-ai-notes")).to_contain_text("too small to read")
    expect(panel).to_contain_text("Generated text")
    # Reviewed, not yet used: the card has not changed.
    expect(alt).to_have_value("")
    expect(caption).to_have_value("")

    panel.locator("#image-ai-alt").fill("Bar chart of weekly sign-ups; week 4 is highest.")
    panel.get_by_label("I checked every number against the image").check()
    panel.get_by_role("button", name="Use this text").click()
    expect(panel).to_be_hidden()

    expect(alt).to_have_value("Bar chart of weekly sign-ups; week 4 is highest.")
    expect(caption).to_have_value("Sign-ups peaked at 212 in week 4.")
    expect(alt).to_be_focused()
    # The card's own pipeline took it from there: validation and the preview.
    image = card.locator(".card__image")
    expect(image).to_have_attribute("alt", "Bar chart of weekly sign-ups; week 4 is highest.")
    expect(card.locator(".card__caption")).to_have_text("Sign-ups peaked at 212 in week 4.")


def test_a_cancelled_draft_is_not_kept(page: Page, base_url: str):
    card = image_card(page, base_url)
    card.get_by_role("button", name="Describe with AI").click()
    page.get_by_role("button", name="Send image and draft").click()
    expect(page.locator("#image-ai-draft")).to_be_visible()
    page.keyboard.press("Escape")

    card.get_by_role("button", name="Describe with AI").click()
    expect(page.locator("#image-ai-draft")).to_be_hidden()
    expect(page.locator("#image-ai-alt")).to_have_value("")
    expect(card.locator('input[name="alt_text"]')).to_have_value("")


def test_a_failure_leaves_the_card_unchanged_and_can_be_retried(page: Page, base_url: str):
    card = image_card(page, base_url)
    card.locator('input[name="alt_text"]').fill("My own description")
    page.route(
        ROUTE,
        lambda route: route.fulfill(
            status=502,
            content_type="application/json",
            body=json.dumps(
                {"error": {"code": "upstream_error", "message": "The model could not be reached."}}
            ),
        ),
    )
    card.get_by_role("button", name="Describe with AI").click()
    page.get_by_role("button", name="Send image and draft").click()
    expect(page.locator("#image-ai-error")).to_have_text("The model could not be reached.")
    expect(card.locator('input[name="alt_text"]')).to_have_value("My own description")

    page.unroute(ROUTE)
    page.get_by_role("button", name="Send image and draft").click()
    expect(page.locator("#image-ai-draft")).to_be_visible()
    expect(page.locator("#image-ai-error")).to_be_hidden()


def test_a_card_deleted_during_review_is_not_resurrected(page: Page, base_url: str):
    card = image_card(page, base_url)
    card.get_by_role("button", name="Describe with AI").click()
    page.get_by_role("button", name="Send image and draft").click()
    expect(page.locator("#image-ai-draft")).to_be_visible()

    # Deleted behind the dialog, as another tab or a script could.
    page.evaluate(
        "document.querySelector('.editor-card button.btn[data-variant=destructive]').click()"
    )
    page.locator("#confirm-delete").get_by_role("button", name="Delete").click()
    expect(page.locator(".editor-card")).to_have_count(0)
    page.get_by_label("I checked every number against the image").check()
    page.locator("#image-ai").get_by_role("button", name="Use this text").click()
    expect(page.locator(".editor-card")).to_have_count(0)
    expect(page.locator("#app-status")).to_contain_text("deleted")


def test_both_steps_pass_an_accessibility_scan(page: Page, base_url: str):
    card = image_card(page, base_url)
    card.get_by_role("button", name="Describe with AI").click()
    page.wait_for_timeout(300)
    assert_clean(page, "image description, consent step")
    page.get_by_role("button", name="Send image and draft").click()
    expect(page.locator("#image-ai-draft")).to_be_visible()
    page.wait_for_timeout(300)
    assert_clean(page, "image description, draft step")


def test_every_figure_must_be_checked_before_use(page: Page, base_url: str):
    """The live model misread small print without flagging it, so the page
    lists the draft's figures itself and waits for the person to check them."""
    card = image_card(page, base_url)
    card.get_by_role("button", name="Describe with AI").click()
    page.get_by_role("button", name="Send image and draft").click()

    panel = page.locator("#image-ai")
    figures = panel.locator("#image-ai-numbers li")
    expect(figures).to_have_text(["4", "212"])
    use = panel.get_by_role("button", name="Use this text")
    expect(use).to_be_disabled()

    check = panel.get_by_label("I checked every number against the image")
    check.check()
    expect(use).to_be_enabled()

    # Changing a figure means the list has not been checked any more.
    panel.locator("#image-ai-caption").fill("Sign-ups peaked at 221 in week 4.")
    expect(figures).to_have_text(["4", "221"])
    expect(check).not_to_be_checked()
    expect(use).to_be_disabled()

    # With no figures left there is nothing to check.
    panel.locator("#image-ai-alt").fill("A bar chart of weekly sign-ups.")
    panel.locator("#image-ai-caption").fill("Sign-ups rose through the month.")
    expect(panel.locator("#image-ai-numbers-block")).to_be_hidden()
    expect(use).to_be_enabled()
