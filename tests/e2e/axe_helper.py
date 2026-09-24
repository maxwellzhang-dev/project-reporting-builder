"""Run the pinned, locally served axe-core build against the current page.

docs/test_plan.md §9: an axe load or execution failure must fail the check, so
nothing here swallows an error into a pass.
"""

from pathlib import Path

from playwright.sync_api import Page

AXE_SOURCE = Path(__file__).resolve().parents[1] / "vendor" / "axe.min.js"


def audit(page: Page, context: str = "document") -> list[dict]:
    """Return serious and critical violations. Raises if axe cannot run."""
    if not AXE_SOURCE.is_file():
        raise RuntimeError(f"axe-core is missing at {AXE_SOURCE}")
    # Evaluated through the DevTools protocol rather than added as a <script>:
    # the page's Content-Security-Policy forbids inline script, correctly, and
    # a test tool must not need the policy loosened to run.
    page.evaluate(AXE_SOURCE.read_text(encoding="utf-8"))
    if not page.evaluate("typeof window.axe === 'object'"):
        raise RuntimeError("axe-core did not load")

    result = page.evaluate(
        """async () => {
            const run = await axe.run(document, {
                resultTypes: ['violations'],
                runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
            });
            return run.violations.map(v => ({
                id: v.id, impact: v.impact, help: v.help,
                nodes: v.nodes.slice(0, 3).map(n => n.target.join(' ')),
            }));
        }"""
    )
    return [v for v in result if v["impact"] in {"serious", "critical"}]


def assert_clean(page: Page, context: str) -> None:
    violations = audit(page, context)
    assert not violations, f"axe found {len(violations)} violation(s) in {context}: {violations}"
