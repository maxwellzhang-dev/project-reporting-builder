"""Clipboard and PNG export, against docs/test_plan.md §8.

The real clipboard is used where the browser allows it; the unavailable and
rejected cases are simulated, and kept in separate tests so a mocked result is
never mistaken for a real one.
"""

import os
import re
import struct

import pytest
from playwright.sync_api import Page, expect

PLAIN = "Payments migration"
SUMMARY = "Login refactor finished; 12 of 18 accounts moved."


def grant_clipboard(page: Page):
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])


def add_progress(page: Page, title=PLAIN, summary=SUMMARY) -> None:
    page.click('[data-add-card="progress"]')
    card = page.locator(".editor-card").first
    card.get_by_label("Title").fill(title)
    card.get_by_label("Summary").fill(summary)
    # Wait for the preview, because sharing uses the current rendered revision.
    expect(card.locator(".card")).to_contain_text(title)


def read_clipboard_text(page: Page) -> str:
    return page.evaluate("navigator.clipboard.readText()")


def wait_for_copy(page: Page, kind: str) -> None:
    """Copying is asynchronous: the card may need re-rendering first. Wait for
    the announcement rather than reading the clipboard into a race."""
    expect(page.locator("#app-status")).to_contain_text(re.compile(f"{kind} copied", re.I))


# --- plain text -----------------------------------------------------------


def test_copy_plain_text_puts_the_exact_card_text_on_the_clipboard(page: Page, base_url: str):
    grant_clipboard(page)
    page.goto(base_url)
    add_progress(page)

    page.locator(".editor-card").first.get_by_role("button", name="Copy text").click()
    wait_for_copy(page, "text")
    text = read_clipboard_text(page)

    assert PLAIN in text
    assert SUMMARY in text
    # Plain text must be plain: no markup leaks in.
    assert "<" not in text


def test_copy_reports_success_to_the_user(page: Page, base_url: str):
    grant_clipboard(page)
    page.goto(base_url)
    add_progress(page)
    page.locator(".editor-card").first.get_by_role("button", name="Copy text").click()
    expect(page.locator("#app-status")).to_contain_text(re.compile("copied", re.I))


# --- rich text ------------------------------------------------------------


@pytest.mark.rich_clipboard
def test_copy_rich_supplies_both_html_and_plain(page: Page, base_url: str):
    grant_clipboard(page)
    page.goto(base_url)
    add_progress(page)

    page.locator(".editor-card").first.get_by_role("button", name="Copy rich").click()
    wait_for_copy(page, "rich text")

    types = page.evaluate("""
      async () => {
        const items = await navigator.clipboard.read();
        return items.flatMap(i => i.types);
      }
    """)
    assert "text/html" in types, types
    assert "text/plain" in types, types

    # The page's CSP makes Chromium report the inline styles as it writes
    # them; they must still arrive, or the card pastes into email unstyled.
    html = page.evaluate("""
      async () => {
        const [item] = await navigator.clipboard.read();
        return await (await item.getType("text/html")).text();
      }
    """)
    assert 'style="' in html


def test_image_cards_offer_no_rich_copy(page: Page, base_url: str):
    """scope.md §6: an image card has no rich-text form."""
    page.goto(base_url)
    page.click('[data-add-card="image"]')
    card = page.locator(".editor-card").first
    expect(card.get_by_role("button", name="Copy text")).to_be_visible()
    expect(card.get_by_role("button", name="Copy rich")).to_have_count(0)


# --- failure paths --------------------------------------------------------


def test_manual_fallback_appears_when_the_clipboard_is_unavailable(page: Page, base_url: str):
    page.goto(base_url)
    page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: undefined})")
    add_progress(page)

    page.locator(".editor-card").first.get_by_role("button", name="Copy text").click()

    fallback = page.get_by_role("dialog", name=re.compile("copy", re.I))
    expect(fallback).to_be_visible()
    # The fallback must carry the current content, not a placeholder.
    expect(fallback.get_by_role("textbox")).to_have_value(re.compile(re.escape(SUMMARY)))


def test_manual_fallback_appears_when_permission_is_refused(page: Page, base_url: str):
    page.goto(base_url)
    page.evaluate("""
      navigator.clipboard.writeText = () => Promise.reject(new Error('denied'));
      navigator.clipboard.write = () => Promise.reject(new Error('denied'));
      null;  // the completion value must not be a function: Playwright would call it
    """)
    add_progress(page)

    page.locator(".editor-card").first.get_by_role("button", name="Copy text").click()
    expect(page.get_by_role("dialog", name=re.compile("copy", re.I))).to_be_visible()


# --- PNG ------------------------------------------------------------------


def png_size(path) -> tuple[int, int]:
    """Width and height from the IHDR chunk, without an image library."""
    with open(path, "rb") as handle:
        header = handle.read(24)
    assert header[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", header[16:24])


# A blank PNG compresses to almost nothing, so bytes per pixel separates an
# image with content from an empty one of exactly the right size. Measured:
# a blank export sat at 0.03, real cards at 0.19 and above. This exists
# because an earlier bug produced correctly sized, entirely white images and
# every dimension assertion passed (docs/test_plan.md §8 warns about exactly
# this, and only looking at the file caught it).
MIN_BYTES_PER_PIXEL = 0.05


def assert_not_blank(path, width, height):
    ratio = os.path.getsize(path) / (width * height)
    assert ratio > MIN_BYTES_PER_PIXEL, f"image looks blank: {ratio:.3f} bytes/pixel"


def test_png_downloads_with_a_usable_name_and_real_pixels(page: Page, base_url: str):
    page.goto(base_url)
    add_progress(page)

    with page.expect_download() as download:
        page.locator(".editor-card").first.get_by_role("button", name="Download PNG").click()
    path = download.value.path()

    assert download.value.suggested_filename.endswith(".png")
    width, height = png_size(path)
    assert width > 100 and height > 50, (width, height)
    assert_not_blank(path, width, height)


def test_png_excludes_the_editing_controls(page: Page, base_url: str):
    """scope.md §6: an export carries the card, not the tools around it."""
    page.goto(base_url)
    add_progress(page)
    card = page.locator(".editor-card").first

    with page.expect_download() as download:
        card.get_by_role("button", name="Download PNG").click()
    width, _ = png_size(download.value.path())

    preview_width = card.locator(".card").bounding_box()["width"]
    editor_width = card.bounding_box()["width"]
    # The image is the preview plus the staging padding, at 2x. Checking the
    # actual number, rather than merely "smaller than the editor", is what
    # shows the controls are outside the snapshot.
    expected = (preview_width + 32) * 2
    assert abs(width - expected) <= 8, (width, expected)
    assert width < editor_width * 2, (width, editor_width)


@pytest.mark.parametrize(
    ("title", "summary"),
    [
        ("付款系统迁移", "登录重构已完成，18 个商户账户中已迁移 12 个。"),
        ("Long content", "Sentence. " * 60),
    ],
)
def test_png_covers_chinese_and_long_content(page: Page, base_url: str, title, summary):
    page.goto(base_url)
    add_progress(page, title, summary)

    with page.expect_download() as download:
        page.locator(".editor-card").first.get_by_role("button", name="Download PNG").click()
    path = download.value.path()
    width, height = png_size(path)
    assert width > 100 and height > 50
    assert_not_blank(path, width, height)


def test_export_failure_keeps_the_card_and_allows_a_retry(page: Page, base_url: str):
    page.goto(base_url)
    add_progress(page)
    button = page.locator(".editor-card").first.get_by_role("button", name="Download PNG")

    # Export once so the library is loaded, then make the render itself fail.
    # The application carries no test hook for this: the failure is injected
    # into the library it actually calls.
    with page.expect_download():
        button.click()
    page.evaluate("""
      window.htmlToImage.toBlob = () => Promise.reject(new Error('boom'));
      null;
    """)

    button.click()

    expect(page.locator("#app-status")).to_contain_text(re.compile("could not|failed", re.I))
    expect(button).to_be_enabled()
    expect(page.locator(".editor-card")).to_have_count(1)
    expect(page.locator(".editor-card").first.get_by_label("Title")).to_have_value(PLAIN)


def test_a_deleted_card_does_not_download(page: Page, base_url: str):
    """docs/architecture.md §7: a card that changes or goes away mid-export
    must not produce a file."""
    page.goto(base_url)
    add_progress(page)
    card = page.locator(".editor-card").first
    button = card.get_by_role("button", name="Download PNG")

    # Load the library, then hold the render open until the test releases it,
    # so the deletion is guaranteed to land while an export is in flight. A
    # fixed delay (900 ms, originally) raced the delete-and-confirm clicks
    # and lost on a slow CI runner once dialogs animated.
    with page.expect_download():
        button.click()
    page.evaluate("""
      const real = window.htmlToImage.toBlob;
      window.htmlToImage.toBlob = (node, opts) =>
        new Promise((resolve) => {
          window.__releaseExport = () => resolve(real(node, opts));
        });
      null;
    """)

    downloads = []
    page.on("download", lambda d: downloads.append(d))
    button.click()
    page.wait_for_function("typeof window.__releaseExport === 'function'")
    card.get_by_role("button", name="Delete").click()
    page.locator("#confirm-delete").get_by_role("button", name="Delete").click()
    expect(page.locator(".editor-card")).to_have_count(0)
    page.evaluate("window.__releaseExport()")

    page.wait_for_timeout(1500)
    assert downloads == [], "a deleted card produced a download"
    expect(page.locator("#app-status")).to_contain_text(re.compile("card|retry|changed", re.I))
