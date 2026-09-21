"""Metric proposals in the AI review panel (docs/scope.md §5).

The feature exists because a status report states its figures in prose, and
the one piece of real computation in this tool is the metric comparison. It is
safe only because a proposal copies stated numbers and never derives one, so
most of these tests are about the figure the model is *not* allowed to supply.
"""

import re

from playwright.sync_api import Page, expect

from tests.e2e.ai_markers import NO_METRICS

NOTE = "Sprint 24. Onboarding completion rose from 67% to 79%. 847 new users, up 23%."


def panel(page: Page):
    return page.get_by_role("dialog", name=re.compile("draft", re.I))


def generate(page: Page, base_url: str, note: str = NOTE):
    page.goto(base_url)
    page.get_by_role("button", name="Paste notes, draft with AI").click()
    panel(page).get_by_label("Project notes").fill(note)
    panel(page).get_by_role("button", name="Generate draft").click()
    expect(panel(page).get_by_label("Draft title")).to_be_visible()


def metrics_group(page: Page):
    return panel(page).get_by_role("group", name=re.compile("metric cards", re.I))


def test_proposals_are_listed_with_their_figures(page: Page, base_url: str):
    generate(page, base_url)
    group = metrics_group(page)
    expect(group).to_be_visible()
    expect(group).to_contain_text("Onboarding completion")
    expect(group).to_contain_text("79%")
    expect(group).to_contain_text("67%")


def test_a_missing_baseline_is_named_rather_than_filled(page: Page, base_url: str):
    """The case the feature turns on: "847, up 23%" states one figure, not two."""
    generate(page, base_url)
    expect(metrics_group(page)).to_contain_text(re.compile("no earlier figure stated", re.I))
    # 688 is 847 divided by 1.23. If it ever appears, the model derived it.
    expect(metrics_group(page)).not_to_contain_text("688")


def test_proposals_start_unticked(page: Page, base_url: str):
    generate(page, base_url)
    for box in metrics_group(page).get_by_role("checkbox").all():
        expect(box).not_to_be_checked()


def test_declining_every_proposal_creates_only_the_progress_card(page: Page, base_url: str):
    generate(page, base_url)
    panel(page).get_by_label("Status").select_option("in_progress")
    panel(page).get_by_role("button", name="Create card").click()

    cards = page.locator(".editor-card")
    expect(cards).to_have_count(1)
    expect(cards.first.locator(".editor-card__heading")).to_have_text("Progress card")


def test_a_ticked_proposal_becomes_an_ordinary_metric_card(page: Page, base_url: str):
    generate(page, base_url)
    metrics_group(page).get_by_role("checkbox").first.check()
    panel(page).get_by_label("Status").select_option("in_progress")
    panel(page).get_by_role("button", name="Create card").click()

    cards = page.locator(".editor-card")
    expect(cards).to_have_count(2)
    metric = cards.nth(1)
    expect(metric.locator(".editor-card__heading")).to_have_text("Metric card")
    expect(metric.get_by_label("Metric name")).to_have_value("Onboarding completion")
    expect(metric.get_by_label("Current value")).to_have_value("79")
    expect(metric.get_by_label("Previous value")).to_have_value("67")
    # The comparison is computed by the application, never by the model.
    expect(metric.locator(".card")).to_contain_text("+12 percentage points")


def test_a_proposal_without_a_baseline_makes_a_current_only_card(page: Page, base_url: str):
    generate(page, base_url)
    metrics_group(page).get_by_role("checkbox").nth(1).check()
    panel(page).get_by_label("Status").select_option("in_progress")
    panel(page).get_by_role("button", name="Create card").click()

    metric = page.locator(".editor-card").nth(1)
    expect(metric.get_by_label("Current value")).to_have_value("847")
    expect(metric.get_by_label("Previous value")).to_have_value("")
    preview = metric.locator(".card")
    expect(preview).to_contain_text("847")
    # No baseline means no comparison at all, not a comparison against zero.
    expect(preview).not_to_contain_text("percentage points")
    expect(preview).not_to_contain_text("relative change")


def test_text_without_figures_proposes_nothing(page: Page, base_url: str):
    generate(page, base_url, f"{NO_METRICS} The team met and agreed to meet again.")
    expect(metrics_group(page)).to_be_hidden()


def test_cancelling_discards_the_proposals(page: Page, base_url: str):
    generate(page, base_url)
    metrics_group(page).get_by_role("checkbox").first.check()
    panel(page).get_by_role("button", name="Cancel").click()

    expect(page.locator(".editor-card")).to_have_count(0)
    page.get_by_role("button", name="Paste notes, draft with AI").click()
    expect(metrics_group(page)).to_be_hidden()
