# Project Reporting Builder — Architecture

> Status: POC baseline  
> Product scope:   [[scope.md]]
> Testing: [[test_plan.md]]

## 1. Technology Stack

| Layer | Technology |
| --- | --- |
| Backend | FastAPI + Pydantic v2 |
| Rendering | Jinja2 |
| Frontend | HTML, CSS, JavaScript ES Modules |
| UI components | Basecoat (shadcn/ui design system, precompiled CSS) and a Lucide icon subset |
| AI | Azure OpenAI through the official Python SDK |
| Local persistence | IndexedDB |
| PNG export | Browser-side library |
| Testing | pytest, pytest-playwright, axe-core |
| Quality | ruff, GitHub Actions |
| Deployment | Docker on Azure Container Apps |

The frontend has no build pipeline. Browser dependencies are pinned and served locally rather than loaded from a runtime CDN.

Basecoat was chosen over React- or Tailwind-based component kits because it ships as a precompiled stylesheet, so it keeps that rule. It is loaded first and lives in cascade layers; `app.css` is unlayered and loaded second, so the application's own rules always win. Two consequences are handled in `app.css` rather than left to chance: Basecoat's reset removes list markers and dialog centring, and it defines a `.card` component whose layout the snippet card must not inherit, since the PNG export is taken from that card. Dark mode follows the operating system through a `dark` class set by `theme.js` before first paint.

## 2. System Design

```text
Browser
  ├── Editor and application state
  ├── IndexedDB: report drafts and image blobs
  ├── Clipboard
  └── PNG export
         │
         ├── Card data ──→ FastAPI ──→ Validation and rendering
         │                              ├── Preview HTML
         │                              ├── Email HTML
         │                              └── Plain text
         │
         └── Source notes ──→ FastAPI ──→ Azure OpenAI
                                             │
                                      Validated AI draft
                                             │
                                      User review
                                             │
                                      Create progress card
```

The page, static assets, and API share one origin.

The server does not persist reports or receive image files.
Azure OpenAI is called only when the user explicitly requests AI assistance.

## 3. Project Structure

```text
app/
  main.py
  config.py
  schemas/
    cards.py
    rendering.py
    ai.py
  domain/
    metrics.py
    presentation.py
  services/
    rendering.py
    plain_text.py
    presentation_model.py
    ai_extraction.py
    azure_provider.py
  errors.py
  templating.py
  prompts/
    extract_progress_v2.txt
  templates/
    index.html
    preview/
      card.html
    email/
      card.html
  static/
    css/
      app.css
    js/
      main.js
      theme.js
      state.js
      api.js
      editor.js
      preview.js
      persistence.js
      image-assets.js
      ai-review.js
      clipboard.js
      export-image.js
      export-report.js
    vendor/            basecoat/, lucide/, html-to-image.js
tests/
  unit/
  integration/
  e2e/
  vendor/              axe-core, test-only
docs/
pyproject.toml
Dockerfile
.dockerignore
.github/workflows/ci.yml
```

Small modules may be combined where this improves clarity.
No agent framework, vector database, or workflow engine is required.

## 4. Data Models

### Card models

Use a Pydantic discriminated union with `type`:

- `ProgressCard`
- `MetricCard`
- `ImageCard`

Common fields:
- `id`: browser-generated UUID.
- `type`: progress, metric, or image.
- `title`: trimmed, non-empty text.

Models reject unknown fields.

Progress status values:

```text
proposed
under_review
cleared_to_start
in_progress
completed
on_hold
cancelled
```

Display labels are separate from API values.

Metric fields include:
- `current`
- `previous`: nullable
- `unit`: number, percent, or custom
- `unit_label`
- `note`

In addition to common fields, ImageCard contains `caption` and `alt_text`.
The API accepts image metadata only, never files, base64 data, remote URLs, or browser Object URLs.

### Initial limits

| Item | Limit |
| --- | --- |
| Cards per report | 20 |
| Title | 120 characters |
| Progress summary | 2,000 characters |
| Each progress list | 8 items, 300 characters per item |
| Metric note | 500 characters |
| Custom unit label | 16 characters |
| Image caption | 1,000 characters |
| Alternative text | 300 characters |
| Image file | 5 MiB |
| Total retained image files | 100 MiB, guaranteed by 20 cards × one 5 MiB image each rather than checked separately |
| Image dimensions | 4,096 pixels per side and 12 million pixels total |
| AI source text | 8,000 characters |
| API request body | 64 KiB |

Image file size does not represent decoded memory usage.
Dimension checks and on-demand image loading are also required.

Browser storage quotas may be lower than application limits.
Storage failures must be handled explicitly.

The backend supplies non-sensitive limits to the frontend.
Backend validation remains authoritative for API inputs.

## 5. Metric Calculation

Calculation is implemented as a pure Python function.

```text
absolute_change = current - previous

relative_change_percent = absolute_change / abs(previous) * 100
```

Rules:
- Missing previous value: no comparison.
- Zero previous value: absolute change and direction remain available;
  relative change is unavailable.
- Negative baselines use their absolute magnitude as the denominator.
- Direction is up, down, or unchanged; it does not imply business value.
- Reject non-finite inputs and non-finite calculation results.
- Reject booleans and numeric strings at the API boundary.

For percentage metrics, `78` represents `78%`.
A change from 65 to 78 is +13 percentage points and +20% relative change.

Calculation does not round results.
A shared presentation module handles:
- Up to two decimal places, rounded half-up.
- Trailing-zero removal.
- Negative-zero normalization.
- Units and percentage points.
- Signed “less than 0.01” labels for tiny nonzero changes.

Preview, email, and plain text use the same presentation model.

## 6. API

### GET /

Returns the application page.

### GET /healthz

```json
{"status": "ok"}
```

This checks basic application availability, not Azure OpenAI availability.

### POST /api/cards/render

Request:

```json
{
  "revision": 3,
  "card": {
    "id": "7f8ea3ac-364a-4e4b-9e5a-2a9a7755bc01",
    "type": "metric",
    "title": "Completion Rate",
    "current": 78,
    "previous": 65,
    "unit": "percent",
    "unit_label": "",
    "note": ""
  }
}
```

Response:

```json
{
  "card_id": "7f8ea3ac-364a-4e4b-9e5a-2a9a7755bc01",
  "revision": 3,
  "preview_html": "<article>...</article>",
  "plain_text": "Completion Rate\n78%\n+13 percentage points\n+20% relative change",
  "rich_html": "<div>...</div>"
}
```

HTML above is illustrative.

For image cards:
- `rich_html` is null.
- `preview_html` contains a controlled image placeholder.
- The browser attaches the local image using DOM APIs.

### POST /api/ai/extract-progress

Request:

```json
{
  "source_text": "Login refactoring is complete. Payment integration is delayed."
}
```

Response:

```json
{
  "draft": {
    "title": "Project Update",
    "summary": "Login refactoring is complete; payment integration is delayed.",
    "completed_items": ["Completed login refactoring"],
    "next_steps": [],
    "risks": ["Payment integration is delayed"]
  },
  "review_notes": [
    "Select the project status before creating the card."
  ]
}
```

The draft does not include a confirmed project status or card ID.
The user supplies the status before creating a normal progress card.

### Errors

Use a consistent envelope:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Review the highlighted fields.",
    "fields": [
      {
        "path": "card.title",
        "message": "Title is required."
      }
    ]
  }
}
```

Status codes:
- 413: request too large.
- 422: invalid input.
- 429: application rate limit reached.
- 502: invalid or failed upstream AI response.
- 503: AI disabled or temporarily unavailable.
- 504: AI timeout.
- 500: unexpected application error.

Do not expose raw Pydantic input, provider responses, credentials, or stack traces.
Enforce request size while reading the body, not only through Content-Length.

## 7. Frontend State and Rendering

The application state is the source of truth, not the DOM.

```text
report
  cards[]
  selectedCardId   reserved: the editor has no card selection, so this is null

assetsByCardId
  blob
  objectUrl
  dimensions

renderStateByCardId
  revision
  renderedRevision
  status
  result
  errors

aiState
  sourceText
  requestVersion
  status
  draft
  reviewNotes
```

### Preview updates

1. Update the local draft immediately.
2. Increment the card revision and mark the old render stale.
3. Debounce text input by approximately 300 ms.
4. Cancel obsolete requests where possible.
5. Accept responses only if card ID and revision still match.

Cancellation alone does not prevent stale responses; revision checks are required.

Sharing is enabled only for the current valid revision.
Image export also requires a valid, decoded image.

Preview updates must not rebuild active form controls or move input focus.

### Export consistency

PNG export uses an isolated snapshot.
If the card changes or is deleted before export completes, discard the result
and ask the user to retry.

Temporary nodes and Object URLs are cleaned up after success or failure.

## 8. Local Draft Persistence

Use IndexedDB for a single working report, not report history.

Stores:
- `reports`: schema version, card order, editable fields, last-saved timestamp, and a `selectedCardId` field kept for a future selection feature (always null today).
- `assets`: image blobs keyed by card ID.

Behavior:
- Autosave editable report state with a short debounce.
- Save image metadata and blobs consistently in one transaction when changed.
- Allow incomplete card fields to be saved.
- Serialize writes so an older save cannot overwrite newer state.
- Restore cards and image blobs on startup.
- Create new Object URLs after restoration; never persist Object URLs.
- Re-render restored cards through the normal validation flow.
- Show Saving, Saved, and Save failed states.
- Provide a Clear local data action.

Do not persist:
- Rendered HTML.
- Azure credentials.
- AI source notes or unconfirmed AI responses.
- Transient requests and loading states.

Confirmed AI content is saved as a normal card.

Storage failures do not discard the active in-memory report.
Warn that recent edits may not survive refresh when saving fails or is pending.

If stored data is corrupt or has an unsupported schema version, show a recovery/reset choice rather than silently deleting it.

Local storage is device- and browser-specific, may be cleared or evicted, and is not a secure vault for sensitive content.

## 9. Azure OpenAI Integration

The backend uses one configured Azure deployment.

Configuration:
- `AI_ENABLED`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT`
- `AZURE_OPENAI_API_KEY`
- API version only if required by the selected SDK/API path.

Pin the SDK and verify the chosen endpoint, API, deployment, and structured
output support together.

### Extraction flow

1. Validate source text.
2. Apply rate and concurrency limits.
3. Send a fixed instruction prompt and a separate source-text message.
4. Request structured output where supported.
5. Validate the response with Pydantic.
6. Return an editable draft.

The prompt requires:
- Source-faithful extraction.
- Preservation of numbers, dates, negation, and uncertainty.
- Separation of completed work, plans, and risks.
- Review notes instead of invented missing facts.
- No HTML, metric calculation, or status assignment.

Source text is untrusted data, not an instruction source.
The model has no tools, browsing, database access, or side effects.

Schema validation checks structure, not factual correctness.
User review is required.

### Failure and cost controls

- Bound input length and output tokens.
- Configure an overall timeout and bounded SDK retries.
- Do not implement an automatic response-repair loop.
- Limit request frequency and concurrent AI calls.
- Disable repeated submission while a request is active.
- Ignore responses for superseded or cancelled source text.
- Keep manual editing available on failure.

For a single-instance POC, an in-process limiter is acceptable with its
restart and multi-instance limitations documented.

Configure cost monitoring and alerts.
Budget alerts are not a guaranteed spending cutoff.

## 10. Output Rendering

### Preview HTML

- Use semantic headings, lists, and articles.
- Explicitly enable Jinja2 autoescaping.
- Never treat user text as template source.
- Do not apply `safe` to user fields.
- Insert only controlled server-rendered HTML into designated preview nodes.

### Email HTML

Use separate templates with simple layout and inline styles.
Do not depend on preview CSS, scripts, or external assets.

### Plain text

Serialize from the presentation model.
Do not generate text by stripping HTML tags.

### Clipboard

Prepare content before the click to preserve browser user activation.
Write both `text/html` and `text/plain` for rich text.

If access fails, show selectable plain text for manual copying.

### PNG

Use a pinned, locally served browser library.
Validate Chinese/English text, long content, local images, and maximum-size cards before selecting it.

Export from a dedicated fixed-width node with an explicit background.
Wait for fonts and images; omit editing controls.

On canvas or rendering limits, fail clearly rather than silently crop.

## 11. Accessibility

- Use native form controls and buttons.
- Associate labels and field errors.
- Preserve visible focus and logical tab order.
- Manage focus after deletion, reordering, and dialogs.
- Announce meaningful copy, export, AI, and save outcomes.
- Avoid announcing the entire preview on every edit.
- Represent status with text as well as color.
- Support mobile layouts and zoom without losing core operations.

## 12. Security and Privacy

- Keep credentials in server environment secrets.
- Do not commit secrets or include them in the image or frontend.
- Do not log report text, AI payloads, or rendered output.
- Disable provider payload tracing unless explicitly reviewed.
- Do not upload image blobs.
- Avoid third-party analytics, remote fonts, and runtime CDNs.
- Set render and AI responses to `Cache-Control: no-store`.
- Use HTTPS and same-origin API access.
- Configure security headers compatible with the selected export library.
- Treat restored local drafts as untrusted input and validate before rendering.

## 13. Deployment and Quality

- Deploy the Docker image to Azure Container Apps.
- Use a non-root production container without development reload.
- Exclude test browsers from the production image.
- Bind the application to `0.0.0.0:8000` and configure the ingress target port as `8000`.
- Store Azure OpenAI credentials in Container Apps secrets and reference them through environment variables.
- Configure HTTPS ingress and health probes.
- Check `/healthz` after deployment.
- Verify resource limits, scaling settings, cold-start behavior, and costs.
- For the POC, use one application worker and a maximum of one replica so in-process AI limits operate within a single process.
- These limits reset on restart and are not a durable spending cap.

CI runs:
1. ruff lint and formatting checks.
2. Unit and API integration tests.
3. Playwright and axe checks.
4. Docker build and health check.

CI uses a fake AI provider, not paid Azure calls.
Real-model quality evaluation runs separately against fixed examples.

## 14. Initial Decisions

| Decision | Action |
| --- | --- |
| PNG library and version | Validate complex card exports |
| Azure deployment and API | Complete a real structured-draft request |
| Azure Container Apps | Deploy the minimal application and verify ingress, secrets, health probes, and costs |
| Browser environment | Record local version and pin CI dependencies |
| Email and messaging clients | Select clients available for manual testing |
| axe-core | Pin and load locally in tests |