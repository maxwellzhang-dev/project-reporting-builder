# Project Reporting Builder — Product Scope

> Status: POC baseline  
> Architecture: [[architecture.md]]  
> Testing: [[test_plan.md]]

## 1. Overview
A lightweight web tool for project managers, tech leads, and business stakeholders to turn project notes, metrics, and images into shareable Snippet Cards.

Users can create cards manually or use Azure OpenAI to structure project notes into an editable draft.

## 2. User Flow
Create a card or load examples → Enter content or generate an AI draft → Edit and preview → Arrange cards → Copy or download

## 3. Core Features
| Feature | Scope |
| --- | --- |
| Card types | Progress, metric, and image |
| Editing | Field editing, validation, and live preview |
| Card management | Create, select, delete, move up, and move down |
| AI assistance | Optional text-to-progress-draft generation through Azure OpenAI |
| Sharing | Plain text, rich text, and single-card PNG |
| Examples | Load a sample report containing all three card types |
| Accessibility | Keyboard operation, labels, visible focus, and accessible feedback |
| Responsive layout | Desktop and mobile layouts |
| Local draft recovery | Automatically save and restore one working report, including images and the selected card, in the current browser |
## 4. Card Types

### Progress Card

Required:
- Title
- Status
- Summary

Optional:
- Completed items
- Next steps
- Risks

Statuses:
- Proposed
- Under Review
- Cleared to Start
- In Progress
- Completed
- On Hold
- Cancelled

Status represents the project stage. Risks are recorded separately.
Empty optional sections are omitted from the output.

### Metric Card

Required:
- Metric name
- Current value
- Unit: number, percentage, or custom

Optional:
- Previous value
- Note

Behavior:
- Without a previous value, display only the current metric.
- With a previous value, display the difference, direction, and relative change where available.
- A zero previous value makes relative change unavailable.
- Direction does not imply business improvement or deterioration.
- Percentage-point differences and relative percentage changes are
  displayed separately.

Calculation and formatting rules are defined in architecture.md.

### Image Card

Required:
- Title
- Image
- Alternative text

Optional:
- Caption

Supported formats: PNG, JPEG, and WebP.

Image files remain in the browser. Invalid files are rejected without replacing an existing valid image.

## 5. AI Assistance
Users can choose manual entry or AI-assisted structuring.

Azure OpenAI converts pasted text into a progress draft containing:
- Title
- Summary
- Completed items
- Next steps
- Risks
- Review notes for missing or ambiguous information

It may also propose metric cards for figures the text states outright. A
proposal copies the numbers as written and never derives one: where the source
gives a current value but no baseline, the previous value is left empty, which
is a normal metric card showing only the current figure (§4). A percentage
change quoted without its baseline is not enough to reconstruct one.

Users review and edit the draft, select the project status, and confirm before
creating a card. Metric proposals are reviewed and confirmed one by one, and
declining them all is an ordinary outcome.

AI assistance:
- Should preserve source facts, numbers, dates, and uncertainty.
- Must not intentionally invent missing information.
- Does not calculate metrics, derive missing values, or generate image cards.
- Does not overwrite existing cards or trigger sharing.
- Preserves the original input when a request fails.
- Provides retry and manual-entry options.

The interface identifies AI output as a draft requiring verification.
Manual editing and sharing remain available when AI is unavailable.

## 6. Sharing

| Card | Plain text | Rich text | PNG |
| --- | --- | --- | --- |
| Progress | Yes | Yes | Yes |
| Metric | Yes | Yes | Yes |
| Image | Title, caption, and alternative text | No | Yes |

- Sharing uses the current valid content, not an outdated preview.
- Rich text targets simple email formatting; appearance varies by client.
- PNG exports exclude editing controls and must not silently crop content.
- Users are encouraged to accompany PNGs with text descriptions.
- Clipboard failures provide a manual-copy fallback.
- Export failures preserve content and allow retry.

Sharing to email, Slack, or Teams uses copy/download workflows, not platform API integrations.

## 7. Data Handling

- No account or server-side report persistence.
- One working report and its images are saved locally using IndexedDB.
- Saved content can be restored in the same browser and origin.
- Pending or failed saves may be lost on refresh.
- Users can clear the locally saved draft; browser data clearing or eviction may also remove it.
- Text, metrics, and image descriptions are sent to the application server for validation and rendering.
- Image files are not uploaded.
- Source notes are sent to Azure OpenAI only when the user requests AI assistance.
- AI source notes and unconfirmed AI responses are not saved locally; confirmed cards are included in the report draft.
- Azure credentials remain on the server.
- Application logs exclude report content and AI request/response bodies.
- Azure data handling follows the selected service configuration and applicable policies.
- Users are advised not to submit sensitive enterprise information to the POC.

> **Changed 2026-09-21.** Metric extraction was previously out of scope. It was
> reinstated in this narrow form after a realistic status report showed the
> cost of leaving it out: the figures stayed trapped in prose while the tool's
> one piece of real computation, the metric comparison, went unused. The
> boundary that mattered was never "no metrics" but "no invented numbers", and
> an empty previous value keeps that boundary without losing the feature.

## 8. Out of Scope

- Authentication, permissions, and collaboration.
- Automatic email or message delivery.
- Jira, Notion, Slack, or Teams API integrations.
- OCR and PDF, Word, Excel, or CSV imports.
- AI image understanding and conversational chat.
- User-provided API keys and model selection.
- Freeform canvas editing and full-report image export.
- Server-side report persistence.
- Multiple saved reports, version history, and cross-device synchronization.

## 9. Deliverables

- Source repository and online demo.
- Docker configuration and CI.
- Automated tests and setup documentation.

