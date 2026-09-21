# Project Reporting Builder

A lightweight web tool that turns project notes, metrics and images into shareable
snippet cards. Cards can be created, edited, reordered and deleted, each with a live
server-rendered preview; drafts survive a reload; and the Azure OpenAI draft
endpoint is implemented behind a provider interface.

Design documents: [`docs/scope.md`](docs/scope.md) ·
[`docs/architecture.md`](docs/architecture.md) · [`docs/test_plan.md`](docs/test_plan.md)

## What works today

| Area | State |
| --- | --- |
| `GET /` application page | Implemented |
| `GET /healthz` | Implemented, returns `{"status": "ok"}` |
| Create, edit, reorder and delete cards | Implemented, 20-card limit, deletion confirmed in a dialog |
| Live preview per card | Implemented, debounced; stale and superseded responses discarded |
| Field-level validation messages | Implemented, wired to `aria-invalid` and `aria-describedby` |
| Local image selection | Implemented: PNG/JPEG/WebP, 5 MB, 4096px per side, 12 MP; files never leave the browser |
| `POST /api/cards/render` | Implemented: preview HTML, email HTML, plain text |
| AI error contract | Implemented: 503 disabled, 429 rate limited, 502 bad upstream, 504 timeout |
| Progress, metric and image card models | Implemented, discriminated union, extra fields rejected |
| Metric comparison and formatting | Implemented as pure functions, covered by the table in `docs/test_plan.md` §3 |
| 64 KiB request limit, `no-store` on responses | Implemented |
| Explicit Jinja2 autoescaping | Implemented, covered by tests |
| Same-origin CSS and ES module JavaScript, no build step | Implemented |
| Semantic markup, skip link, visible focus, status shown as text | Implemented |
| Production Docker image, non-root, no reload | Implemented |
| ruff lint and format, pytest, CI with a container smoke test | Implemented |
| Local draft recovery (IndexedDB) | Implemented: text, order and image blobs, serialised writes, Clear local data |
| `POST /api/ai/extract-progress` | Implemented behind a provider interface; **needs an Azure OpenAI deployment to run live** |
| Documented error envelope | Implemented: `{error:{code,message,fields}}`, never echoes submitted input |
| Playwright browser tests | Implemented: editor, persistence and axe-core scans (21 checks) |

## Planned, not built

Clipboard and PNG export · example report loading · the AI review interface
(the endpoint exists; the browser flow does not) · Azure Container Apps
deployment · a live AI evaluation against the fixed examples in
`docs/test_plan.md` §7.

Nothing in the interface pretends these exist. Scope for each is defined in
`docs/scope.md`; do not infer support from the page.

## Requirements

- Python 3.13
- Docker, only for the container workflow

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock.txt
.venv/bin/uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000>. If port 8000 is taken, add `--port 8001`.

## Tests and linting

```bash
.venv/bin/pytest                          # unit + integration
.venv/bin/pytest tests/e2e --browser chromium   # browser tests
.venv/bin/ruff check .                    # lint
.venv/bin/ruff format --check .           # formatting
```

Browser tests need Chromium once: `.venv/bin/playwright install chromium`.
The fixture starts the application on a free port and waits for `/healthz`.

## Docker

```bash
docker build -t project-reporting-builder .
docker run --rm -p 8000:8000 project-reporting-builder
curl -fsS http://localhost:8000/healthz
```

The image runs as the non-root user `appuser` (uid 10001), binds `0.0.0.0:8000`,
runs a single uvicorn worker with no reload, and contains neither the test suite
nor a browser. `.dockerignore` keeps `tests/`, `docs/`, the vendored axe build and
local environment files out of the build context.

## Configuration

Copy `.env.example` to `.env`. With `AI_ENABLED=false` the application starts
normally and never contacts Azure OpenAI; the AI endpoint then returns 503.

| Variable | Purpose |
| --- | --- |
| `AI_ENABLED` | Turns the AI draft endpoint on |
| `AZURE_OPENAI_ENDPOINT` | `https://<resource>.openai.azure.com/` |
| `AZURE_OPENAI_DEPLOYMENT` | The deployment name, not the model name |
| `AZURE_OPENAI_API_KEY` | Key, supplied as a container secret in deployment |

Tests never call a real model: they inject a fake provider, so the suite runs
with no credentials and no spend.

Never commit a filled-in `.env`. Credentials belong in environment secrets, not
in the image or in any frontend asset.

## Dependencies

`requirements.in` and `requirements-dev.in` list direct dependencies with exact
versions. The committed `requirements.lock.txt` and `requirements-dev.lock.txt`
pin the full resolved tree, including transitive packages, and are what both the
image and CI install. Regenerate after editing an `.in` file:

```bash
python3 -m venv /tmp/lockenv
/tmp/lockenv/bin/pip install -r requirements.in
/tmp/lockenv/bin/pip freeze > requirements.lock.txt
```

## Layout

```text
app/
  main.py            routes: GET /, GET /healthz, POST /api/cards/render
  config.py          settings, read from the environment
  templating.py      the single Jinja2 environment, autoescaping on explicitly
  errors.py          one error envelope for the whole API
  schemas/           card, render and AI models
  domain/            metric comparison and number formatting, both pure
  services/          presentation model, plain text, rendering, AI extraction
  prompts/           the versioned extraction prompt
  templates/         index.html, preview/card.html, email/card.html
  static/js          state, api, editor, preview, image-assets, persistence, main
  static/vendor      pinned axe-core, used by the accessibility tests only
tests/
  unit/              escaping, metric table, formatting, card validation
  integration/       endpoints, page content, static assets, render API
  e2e/               editing, deletion, focus, async consistency, persistence, axe scans
docs/                scope, architecture, test plan
```

## AI assistance

This project was built with Claude Code. I designed the architecture, wrote the
scope, architecture and test-plan documents that drive it, decided every
trade-off recorded in them, and reviewed each change before it landed. The test
suite is the check on that: the metric table, the escaping rules and the error
contract were written as tests first, and several defects found during
development — a preview that rebuilt the form on every keystroke, focus landing
on a disabled control after deletion, element ids that were not valid CSS
selectors — were caught by those tests rather than by inspection.

The application's own AI feature (Azure OpenAI draft extraction) is separate and
is described under Configuration.

## Attribution

The container and deployment patterns were informed by
[`Azure-Samples/openai-chat-app-quickstart`](https://github.com/Azure-Samples/openai-chat-app-quickstart)
(MIT). No code was copied from it: that sample runs Quart on gunicorn behind
managed identity, while this project runs FastAPI on uvicorn with key-based
configuration, so the Dockerfile here was written against this project's own
requirements.
