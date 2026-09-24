# Project Reporting Builder — Test Plan

> Status: Planned; results are recorded separately  
> Product scope: [[scope.md]]  
> Architecture: [[architecture.md]]

## 1. Test Strategy

| Layer | Tools | Focus |
| --- | --- | --- |
| Unit | pytest | Validation, calculations, formatting, serialization |
| Integration | pytest + FastAPI TestClient | API contracts, templates, errors, AI adapter |
| End-to-end | pytest-playwright | Editing, persistence, AI review, sharing |
| Accessibility | axe-core + manual checks | Semantics, keyboard, focus, feedback |
| AI evaluation | Fixed inputs + real Azure deployment | Factual accuracy and extraction quality |
| Deployment | Docker + Azure Container Apps | Startup, configuration, health, online workflows |

Use fictional project data and non-sensitive images.

CI uses a fake AI provider. Real Azure calls run separately and are never
required for routine CI.

## 2. TDD Approach

Use test-first development for:
- Card validation.
- Metric calculation and formatting.
- Plain-text serialization.
- Output escaping.
- AI response validation and error mapping.

Cycle:
1. Write a test for one expected behavior.
2. Confirm it fails for the intended reason.
3. Implement the smallest working change.
4. Refactor and rerun tests.

Visual layout, PNG library selection, and external-client compatibility
start with experiments, followed by regression tests.

## 3. Unit Tests

### Card Validation

- Accept valid progress, metric, and image metadata models.
- Reject unknown card types and extra fields.
- Validate UUIDs, status values, units, and revisions.
- Reject blank required fields after trimming.
- Check field lengths and list counts at and beyond their limits.
- Require a custom unit label when applicable.
- Reject image files, base64 data, and URLs in API models.
- Reject numeric strings, booleans, NaN, and Infinity as metric values.
- Distinguish a missing previous value from zero.

### Metric Calculation

| Input or condition | Expected result |
| --- | --- |
| Current 120, previous 100 | Difference +20; relative +20%; up |
| Current 80, previous 100 | Difference -20; relative -20%; down |
| Current 100, previous 100 | Difference 0; relative 0%; unchanged |
| Current 0, previous 100 | Difference -100; relative -100% |
| Current 10, previous 0 | Difference +10; relative unavailable |
| Current 0, previous 0 | Difference 0; relative unavailable |
| Previous missing | No comparison |
| Current -80, previous -100 | Difference +20; relative +20% |
| Current -120, previous -100 | Difference -20; relative -20% |
| Current 0.3, previous 0.2 | Approximately +0.1 and +50% |
| Non-finite input or result | Controlled validation error |

Use approximate assertions for floating-point calculations.

### Presentation and Serialization

- Percentage values use the documented scale: 78 means 78%.
- A change from 65% to 78% shows +13 percentage points and +20% relative change.
- Formatting removes unnecessary trailing zeros and negative zero.
- Tiny nonzero changes retain their direction without displaying a misleading zero.
- Empty optional sections are omitted.
- Preview, email, and plain text express the same values.
- Generated labels do not leak missing-value or non-finite markers.
- User text containing HTML or template syntax remains data, not executable content.

### AI Response Validation

Using fake responses:
- Accept a valid draft.
- Reject malformed JSON, incorrect types, unknown fields, and oversized output.
- Handle refusal, empty, and truncated responses without creating a card.
- Treat returned HTML or template-like text as untrusted text.
- Validate bounded review notes as well as card fields.

## 4. API and Template Integration

| Scenario | Expected behavior |
| --- | --- |
| GET / | Application page and required local assets are available |
| GET /healthz | Returns 200 without requiring Azure OpenAI |
| Valid render request | Returns matching card ID, revision, and output fields |
| Image render request | Returns metadata preview and null rich HTML |
| Invalid fields | Returns 422 with usable field paths |
| Malformed JSON | Returns a controlled error |
| Request exceeding 64 KiB | Returns 413 |
| Template/script payload | Escaped and not executed |
| Calculation overflow | Controlled validation error |
| Unexpected exception | Generic error without stack trace or input data |
| Render or AI response | Includes Cache-Control: no-store |

Verify request-size enforcement through the actual application boundary,
including requests where Content-Length cannot be relied upon.

### AI Endpoint

Use a fake provider to verify:
- Valid source text produces a validated draft.
- Invalid input is rejected before contacting the provider.
- AI disabled returns 503.
- Application rate limiting returns 429.
- Invalid upstream output returns 502.
- Timeout returns 504.
- Temporary provider unavailability follows the documented error mapping.
- Errors do not expose credentials, raw provider responses, or source notes.

Inject a distinctive test string and verify it does not appear in application
logs. This does not establish the behavior of Azure platform logs.

## 5. Browser Workflows

### Editing and Card Management

- Create and edit all three card types.
- Display field-level validation errors.
- Preserve focus during preview updates.
- Reorder cards without changing their IDs or associated images.
- Confirm deletion and place focus appropriately afterward.
- Enforce the 20-card limit.
- Confirm before replacing existing content with examples.

### Async Consistency

Control API response timing to verify:
- An older response cannot replace a newer preview.
- A deleted card cannot reappear when its request completes.
- Invalid or pending edits cannot share a previous valid result.
- Network failures preserve input and provide retry feedback.
- A changed or deleted card does not download an outdated PNG.

### Images

- Accept valid PNG, JPEG, and WebP files.
- Reject unsupported, corrupt, oversized, and over-dimension images.
- Enforce the total retained file-size limit.
- Preserve the existing image when replacement fails.
- Release obsolete Object URLs.
- Confirm image files and Object URLs do not appear in API requests.
- Check large-image behavior for obvious memory or responsiveness problems.

## 6. Local Persistence

Use isolated browser contexts between tests. Reload the same context when
testing recovery.

Verify:
- Text fields, order, and incomplete drafts recover after reload.
- Image blobs recover with new Object URLs.
- Restored cards pass through normal validation and rendering.
- “Saved” appears only after the write transaction succeeds.
- Delayed writes cannot overwrite newer edits.
- Image replacement updates metadata and blobs consistently.
- Deletion removes the associated stored image.
- Clear local data removes the draft and assets.
- Pending autosave cannot recreate data after it has been cleared.
- Storage denial, quota errors, and aborted transactions show save failure
  without discarding in-memory content.
- Corrupt or unsupported stored data prompts recovery/reset rather than
  silent deletion.
- Rendered HTML, credentials, AI source notes, and unconfirmed AI responses
  are not persisted.
- Confirmed AI cards are saved as ordinary cards.

Multi-tab editing is not a collaboration feature. Document its behavior
rather than implying cross-tab conflict resolution.

## 7. AI Review Workflow

With a fake provider:
- AI is called only after explicit user action.
- Submitting disables duplicate requests.
- Generated content appears as a draft requiring review.
- Users can edit the draft and must select a project status.
- Confirmation creates a new card.
- Existing cards are not overwritten.
- Cancelled or superseded responses are ignored.
- Failure preserves the source text and offers retry or manual entry.
- Manual editing and sharing remain available when AI is disabled.

### Real Azure Evaluation

Maintain approximately 10–15 fixed examples covering:
- Typical project updates.
- Completed versus unfinished work.
- Planned versus already completed activities.
- Numbers, dates, negation, and uncertainty.
- Missing information.
- Conflicting statements.
- Unrelated text.
- Instructions embedded in source text that attempt to override extraction.

Evaluate meaning rather than exact wording:
- No unsupported facts.
- No changed numbers or dates.
- No plans presented as completed work.
- Important risks retained.
- Ambiguity surfaced for review.
- No model-assigned project status.

Record deployment/model details, prompt version, date, outputs, and findings.
Passing a finite sample does not guarantee future factual accuracy.

## 8. Sharing and PNG

### Clipboard

Controlled tests:
- Verify exact plain-text content.
- Verify rich copying supplies both text/html and text/plain.
- Simulate unavailable APIs and rejected permissions.
- Confirm the manual-copy fallback contains current content.

Browser integration:
- Exercise the real clipboard where supported by the test environment.
- Keep mocked and real-clipboard results separate.

### PNG

Use the real export library:
- Verify a download occurs with a valid filename.
- Decode the file and check nonzero dimensions and expected width.
- Cover Chinese/English text, long content, images, and maximum allowed content.
- Verify controls and error messages are excluded.
- Simulate export failure and confirm retry remains available.

File decoding alone cannot detect cropping or missing text.
Inspect representative exports visually.

### External Clients

Manually test at least:
- One email client.
- One messaging client, such as Slack or Teams.

Record client/browser versions and:
- Plain-text completeness.
- Rich-text formatting retained or removed.
- PNG attachment/send behavior.
- Known limitations.

Do not infer compatibility with other clients from one successful test.

## 9. Accessibility and Responsive Layout

Run pinned, locally loaded axe-core against:
- Empty editor.
- Populated cards.
- Validation errors.
- AI review.
- Confirmation dialogs.
- Manual-copy fallback.
- Mobile-width layout.

An axe load or execution failure must fail the check.

Manually verify:
- Logical keyboard order and visible focus.
- No keyboard traps.
- All core actions work without a mouse.
- Labels and error associations are understandable.
- Focus returns appropriately after dialogs and deletion.
- Save, AI, copy, and export feedback is announced without excessive repetition.
- Status does not rely on color alone.
- Approximately 360px width and 200% zoom preserve core operations.
- Text contrast meets the intended requirements.
- One screen reader can complete the main workflow.

Record the actual browser, operating system, and screen reader.
Automated scans do not establish full WCAG compliance.

## 10. CI and Test Execution

Expected commands:

```bash
ruff check .
ruff format --check .
pytest tests/unit tests/integration
pytest tests/e2e --browser chromium
docker build -t project-reporting-builder .
```

The repository must document dependency installation, Playwright browser
setup, and local axe assets.

E2E fixtures start the application, wait for /healthz, and stop it afterward.

CI:
1. Installs locked dependencies and browser assets.
2. Runs lint, formatting, unit, and integration checks.
3. Runs browser and accessibility tests.
4. Builds and smoke-tests the container.

Capture traces and screenshots on failure.
Use conditional waits rather than fixed sleeps.
Review snapshot changes; do not automatically accept them.

## 11. Azure Deployment Checks

- Container runs as non-root without development reload.
- Application binds to 0.0.0.0:8000; ingress targets port 8000.
- HTTPS and health probes work.
- Azure credentials are supplied through secrets, not frontend assets or images.
- One worker and at most one replica match the in-process limiter assumption.
- Cold start and configured resource limits are checked.
- Online editing, local recovery, copying, and PNG download work.
- One real AI request succeeds in the deployed environment.
- Manual workflows remain available during AI failure.

## 12. Release Record

Record results in docs/test-report.md:

```markdown
# Test Report

- Commit:
- Date:
- Deployment URL:
- Browser / OS:
- Azure deployment:
- Prompt version:

## Automated Checks
| Check | Status | Evidence |
| --- | --- | --- |

## Manual Checks
| Scenario | Environment | Status | Notes |
| --- | --- | --- | --- |

## AI Evaluation
| Case | Status | Findings |
| --- | --- | --- |

## Known Issues
| Issue | Impact | Workaround |
| --- | --- | --- |
```

Use explicit statuses: Passed, Failed, Blocked, or Not run.

Incorrect metrics, executable user content, stale sharing, broken core
workflows, and silent loss of confirmed saved data block release.
Document unverified environments and remaining limitations.
