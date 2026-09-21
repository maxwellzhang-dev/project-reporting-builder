"""The AI review workflow, one test per requirement in docs/test_plan.md §7.

The provider is the scripted fake in tests/e2e/ai_app.py, so nothing here
reaches Azure or costs anything.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.ai_app import FILTERED, MALFORMED, SLOW, TIMEOUT

NOTE = "Week 38 payments migration. Login refactor done, 12 of 18 accounts moved."


@pytest.fixture
def page_at(page: Page, base_url: str) -> Page:
    page.goto(base_url)
    return page


def panel(page: Page):
    """The review dialog. Queries are scoped to it: a progress card in the
    list carries a "Status" label too, so an unscoped lookup is ambiguous."""
    return page.get_by_role("dialog", name=re.compile("draft", re.I))


def open_panel(page: Page):
    page.get_by_role("button", name="Draft from notes").click()
    expect(panel(page)).to_be_visible()
    return panel(page)


def generate(page: Page, note: str = NOTE) -> None:
    panel(page).get_by_label("Project notes").fill(note)
    panel(page).get_by_role("button", name="Generate draft").click()


def test_ai_is_called_only_after_an_explicit_action(page_at: Page):
    calls = []
    page_at.on("request", lambda r: calls.append(r.url) if "extract-progress" in r.url else None)

    open_panel(page_at)
    panel(page_at).get_by_label("Project notes").fill(NOTE)
    page_at.wait_for_timeout(600)  # longer than any debounce in the editor
    assert calls == [], "typing notes must not call the model"

    panel(page_at).get_by_role("button", name="Generate draft").click()
    expect(panel(page_at).get_by_label("Draft title")).to_be_visible()
    assert len(calls) == 1


def test_submitting_disables_a_duplicate_request(page_at: Page):
    calls = []
    page_at.on("request", lambda r: calls.append(r.url) if "extract-progress" in r.url else None)

    open_panel(page_at)
    generate(page_at, f"{SLOW}\n{NOTE}")
    button = panel(page_at).get_by_role("button", name="Generate draft")
    expect(button).to_be_disabled()
    expect(panel(page_at).get_by_label("Draft title")).to_be_visible(timeout=10_000)
    assert len(calls) == 1


def test_output_is_presented_as_a_draft_to_review(page_at: Page):
    open_panel(page_at)
    generate(page_at)
    # Named as a draft needing review, not as a finished card.
    expect(panel(page_at)).to_contain_text(re.compile("review", re.I))
    # The model's own uncertainty is shown rather than dropped.
    expect(panel(page_at)).to_contain_text("No date was given for the credential rotation")


def test_the_draft_can_be_edited_before_it_becomes_a_card(page_at: Page):
    open_panel(page_at)
    generate(page_at)
    panel(page_at).get_by_label("Draft title").fill("Edited title")
    panel(page_at).get_by_label("Status").select_option("in_progress")
    panel(page_at).get_by_role("button", name="Create card").click()

    expect(page_at.locator("#card-list .editor-card")).to_have_count(1)
    expect(page_at.locator("#card-list").get_by_label("Title")).to_have_value("Edited title")


def test_a_status_must_be_chosen_before_confirming(page_at: Page):
    open_panel(page_at)
    generate(page_at)
    # The model is forbidden from assigning a status (docs/scope.md §5), so the
    # user has to, and cannot confirm until they do.
    expect(panel(page_at).get_by_label("Status")).to_have_value("")
    expect(panel(page_at).get_by_role("button", name="Create card")).to_be_disabled()

    panel(page_at).get_by_label("Status").select_option("on_hold")
    expect(panel(page_at).get_by_role("button", name="Create card")).to_be_enabled()


def test_confirming_creates_a_card_and_overwrites_nothing(page_at: Page):
    page_at.get_by_role("button", name="Add progress card").click()
    existing = page_at.locator("#card-list .editor-card").first
    existing.get_by_label("Title").fill("Hand-written card")

    open_panel(page_at)
    generate(page_at)
    panel(page_at).get_by_label("Status").select_option("completed")
    panel(page_at).get_by_role("button", name="Create card").click()

    cards = page_at.locator("#card-list .editor-card")
    expect(cards).to_have_count(2)
    expect(cards.first.get_by_label("Title")).to_have_value("Hand-written card")
    expect(cards.nth(1).get_by_label("Title")).to_have_value(re.compile("Draft for"))


def test_cancelling_discards_the_draft_and_creates_nothing(page_at: Page):
    open_panel(page_at)
    generate(page_at)
    panel(page_at).get_by_role("button", name="Cancel").click()

    expect(page_at.locator("#card-list .editor-card")).to_have_count(0)
    open_panel(page_at)
    # A cancelled draft must not be waiting when the panel is reopened.
    expect(panel(page_at).get_by_label("Draft title")).to_be_hidden()
    expect(panel(page_at).get_by_label("Project notes")).to_have_value("")


def test_a_superseded_response_is_ignored(page_at: Page):
    open_panel(page_at)
    generate(page_at, f"{SLOW}\nfirst request")
    panel(page_at).get_by_role("button", name="Cancel").click()

    open_panel(page_at)
    generate(page_at, "second request")
    expect(panel(page_at).get_by_label("Draft title")).to_have_value(re.compile("second request"))
    # Give the slow first response time to land; it must not replace this one.
    page_at.wait_for_timeout(2_000)
    expect(panel(page_at).get_by_label("Draft title")).to_have_value(re.compile("second request"))


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        (TIMEOUT, re.compile("too long", re.I)),
        (MALFORMED, re.compile("unreadable|did not match", re.I)),
        (FILTERED, re.compile("content filter", re.I)),
    ],
)
def test_failure_keeps_the_source_text_and_offers_a_retry(page_at: Page, marker, expected):
    open_panel(page_at)
    note = f"{marker}\n{NOTE}"
    generate(page_at, note)

    expect(panel(page_at).get_by_role("alert")).to_contain_text(expected)
    # The user's text survives the failure (docs/scope.md §5).
    expect(panel(page_at).get_by_label("Project notes")).to_have_value(note)
    expect(panel(page_at).get_by_role("button", name="Generate draft")).to_be_enabled()
    expect(page_at.locator("#card-list .editor-card")).to_have_count(0)


def test_source_notes_and_unconfirmed_drafts_are_not_persisted(page_at: Page):
    open_panel(page_at)
    generate(page_at, "SECRET_NOTE_MARKER payments migration")
    page_at.wait_for_timeout(800)  # longer than the autosave debounce

    stored = page_at.evaluate("""
      async () => {
        const db = await new Promise((resolve, reject) => {
          const request = indexedDB.open('project-reporting-builder');
          request.onsuccess = () => resolve(request.result);
          request.onerror = () => reject(request.error);
        });
        if (!db.objectStoreNames.contains('reports')) return '';
        return await new Promise((resolve) => {
          const all = db.transaction('reports').objectStore('reports').getAll();
          all.onsuccess = () => resolve(JSON.stringify(all.result ?? []));
          all.onerror = () => resolve('');
        });
      }
    """)
    assert "SECRET_NOTE_MARKER" not in stored
    assert "Draft for" not in stored
