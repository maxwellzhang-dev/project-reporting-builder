# vendor (runtime)

Third-party browser assets the application page loads, pinned and served from
this origin rather than a CDN (docs/architecture.md §1). These ship inside the
container image.

| File | Version | Source | Licence |
| --- | --- | --- | --- |
| `html-to-image.js` | 1.11.13 | https://cdn.jsdelivr.net/npm/html-to-image@1.11.13/dist/html-to-image.js | MIT |
| `basecoat/basecoat.min.css` | 1.0.2 | `dist/basecoat.cdn.min.css` from https://registry.npmjs.org/basecoat-css/-/basecoat-css-1.0.2.tgz | MIT |
| `lucide/icons.svg` | 1.47.0 | 12 icons from `icons/` in the lucide-static npm package, combined into one `<symbol>` sprite | ISC |

sha256 of `html-to-image.js`: `a90b42909d80964269ef6d5f...` (first 24 characters;
run `shasum -a 256` to check the whole digest).

sha256 of `basecoat/basecoat.min.css`: `8123677adb9bba43be3298e1...`, identical to the
file in the published package.

Test-only assets live in `tests/vendor/` instead, so that excluding tests from
the image cannot accidentally exclude something the page needs at runtime.
