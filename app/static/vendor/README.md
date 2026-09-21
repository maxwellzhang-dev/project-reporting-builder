# vendor (runtime)

Third-party browser assets the application page loads, pinned and served from
this origin rather than a CDN (docs/architecture.md §1). These ship inside the
container image.

| File | Version | Source | Licence |
| --- | --- | --- | --- |
| `html-to-image.js` | 1.11.13 | https://cdn.jsdelivr.net/npm/html-to-image@1.11.13/dist/html-to-image.js | MIT |

sha256 of `html-to-image.js`: `a90b42909d80964269ef6d5f...` (first 24 characters;
run `shasum -a 256` to check the whole digest).

Test-only assets live in `tests/vendor/` instead, so that excluding tests from
the image cannot accidentally exclude something the page needs at runtime.
