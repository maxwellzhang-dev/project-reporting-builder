# vendor (tests)

Third-party assets used only by the test suite. They are deliberately not under
`app/static/`: the container image excludes `tests/`, and anything the page
needs at runtime must not be excluded with it.

| File | Version | Source | Licence |
| --- | --- | --- | --- |
| `axe.min.js` | 4.10.2 | https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js | MPL-2.0 |

axe-core is injected into the page by Playwright from this path. The
application never loads it.
