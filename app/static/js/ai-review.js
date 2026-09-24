// The AI draft panel: notes in, a reviewable draft out, a card only after the
// user confirms. The rules it enforces are docs/test_plan.md §7 and
// docs/scope.md §5.
//
// Three properties are deliberate rather than incidental:
//
//   1. Nothing here touches an existing card. A confirmed draft goes through
//      addCard/updateCard exactly as a hand-written card does, so an AI card
//      is an ordinary card from the moment it exists.
//   2. The source notes and the unconfirmed draft live in this module only.
//      They never enter the report state, so persistence cannot see them and
//      cannot write them to IndexedDB (scope §7).
//   3. Every response carries the request number that asked for it. A reply
//      that is not the current one is dropped, so a slow first answer cannot
//      overwrite a second, and a cancelled request cannot come back.
//   4. An image is optional and stays in this module like the notes: it
//      is sent, as a downscaled JPEG, only with Generate, and never saved.
//      When the draft was read from one, every figure in it is listed and
//      Create waits until the person says they checked them, because the
//      live model has misread small print without saying so.

import { acceptImage, ImageRejected } from "./image-assets.js";
import { downscaleToJpeg, figuresIn } from "./image-describe.js";
import { addCard } from "./state.js";

const MAX_ITEMS = 8;

const panel = document.getElementById("ai-review");
const openButton = document.getElementById("open-ai-review");
const source = document.getElementById("ai-source");
const generateButton = document.getElementById("ai-generate");
const cancelButton = document.getElementById("ai-cancel");
const createButton = document.getElementById("ai-create");
const errorLine = document.getElementById("ai-error");
const busyLine = document.getElementById("ai-busy");
const draftSection = document.getElementById("ai-draft");
const notesBlock = document.getElementById("ai-notes-block");
const notesList = document.getElementById("ai-notes");
const statusSelect = document.getElementById("ai-draft-status");
const metricsBlock = document.getElementById("ai-metrics-block");
const metricsList = document.getElementById("ai-metrics");
const imageInput = document.getElementById("ai-image");
const imagePreview = document.getElementById("ai-image-preview");
const imageThumb = document.getElementById("ai-image-thumb");
const imageRemove = document.getElementById("ai-image-remove");
const imageError = document.getElementById("ai-image-error");
const numbersBlock = document.getElementById("ai-numbers-block");
const numbersList = document.getElementById("ai-numbers");
const numbersChecked = document.getElementById("ai-numbers-checked");

// The attached image, if any: validated metadata plus an Object URL.
let notesImage = null;
// Whether the draft on screen was read from an image, and the figures
// listed for checking.
let draftFromImage = false;
let listedFigures = [];

// Proposals currently on screen, alongside the checkbox that accepts each.
let metricProposals = [];

const UNIT_SUFFIX = { percent: "%", number: "", custom: "" };

/** How a proposed figure reads before it becomes a card. */
function describeMetric(metric) {
  const suffix = metric.unit === "custom" ? ` ${metric.unit_label ?? ""}`.trimEnd() : UNIT_SUFFIX[metric.unit] ?? "";
  const current = `${metric.current}${suffix}`;
  if (metric.previous === null || metric.previous === undefined) {
    // Named explicitly. A silent absence would look like an oversight rather
    // than the deliberate refusal to invent a baseline that it is.
    return `${current} — no earlier figure stated, so the card shows the current value only`;
  }
  return `${current}, from ${metric.previous}${suffix}`;
}

function showMetrics(metrics) {
  metricProposals = [];
  metricsList.replaceChildren();
  if (!metrics?.length) {
    metricsBlock.hidden = true;
    return;
  }

  for (const [index, metric] of metrics.entries()) {
    const item = document.createElement("li");
    const id = `ai-metric-${index}`;

    const box = document.createElement("input");
    box.type = "checkbox";
    box.className = "input";
    box.id = id;

    const label = document.createElement("label");
    label.htmlFor = id;
    // textContent throughout: a proposed title is model output and stays data.
    label.textContent = `${metric.title}: ${describeMetric(metric)}`;

    item.append(box, label);
    metricsList.append(item);
    metricProposals.push({ metric, box });
  }
  metricsBlock.hidden = false;
}

const fields = {
  title: document.getElementById("ai-draft-title"),
  summary: document.getElementById("ai-draft-summary"),
  completed: document.getElementById("ai-draft-completed"),
  next_steps: document.getElementById("ai-draft-next"),
  risks: document.getElementById("ai-draft-risks"),
};

// Identifies the request whose answer may be applied. Bumped by every new
// request and by cancelling, which is what makes a stale reply detectable.
let currentRequest = 0;

function showError(message) {
  errorLine.textContent = message;
  errorLine.hidden = false;
}

function clearError() {
  errorLine.textContent = "";
  errorLine.hidden = true;
}

function setBusy(busy) {
  generateButton.disabled = busy;
  generateButton.setAttribute("aria-busy", String(busy));
  busyLine.textContent = busy ? "Generating a draft…" : "";
}

async function attachNotesImage(file) {
  try {
    const image = await acceptImage(file);
    if (notesImage) URL.revokeObjectURL(notesImage.objectUrl);
    notesImage = image;
    imageThumb.src = image.objectUrl;
    imagePreview.hidden = false;
    imageError.hidden = true;
  } catch (rejection) {
    // An existing image survives a rejected replacement.
    imageError.textContent =
      rejection instanceof ImageRejected ? rejection.message : "That file could not be used.";
    imageError.hidden = false;
  } finally {
    imageInput.value = "";
  }
}

function clearNotesImage() {
  if (notesImage) URL.revokeObjectURL(notesImage.objectUrl);
  notesImage = null;
  imageThumb.removeAttribute("src");
  imagePreview.hidden = true;
  imageError.hidden = true;
  imageInput.value = "";
}

/** Create needs a status, and for a draft read from an image, checked figures. */
function updateCreate() {
  const figuresPending = draftFromImage && listedFigures.length > 0 && !numbersChecked.checked;
  createButton.disabled = !statusSelect.value || figuresPending;
}

/** List the figures in the draft and its proposals; a changed list is unchecked. */
function refreshFigures() {
  if (!draftFromImage) {
    listedFigures = [];
    numbersBlock.hidden = true;
    updateCreate();
    return;
  }
  const text = [
    ...Object.values(fields).map((control) => control.value),
    ...metricProposals.map(({ metric }) => `${metric.title}: ${describeMetric(metric)}`),
  ].join("\n");
  const figures = figuresIn(text);
  if (figures.join("\u0000") !== listedFigures.join("\u0000")) {
    listedFigures = figures;
    numbersChecked.checked = false;
    numbersList.replaceChildren(
      ...figures.map((figure) => {
        const item = document.createElement("li");
        item.textContent = figure;
        return item;
      }),
    );
  }
  numbersBlock.hidden = figures.length === 0;
  updateCreate();
}

function hideDraft() {
  draftSection.hidden = true;
  for (const control of Object.values(fields)) control.value = "";
  notesList.replaceChildren();
  notesBlock.hidden = true;
  showMetrics([]);
  statusSelect.value = "";
  createButton.disabled = true;
  draftFromImage = false;
  listedFigures = [];
  numbersList.replaceChildren();
  numbersChecked.checked = false;
  numbersBlock.hidden = true;
}

function linesToList(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, MAX_ITEMS);
}

function showDraft(body, { fromImage = false } = {}) {
  const draft = body.draft ?? {};
  fields.title.value = draft.title ?? "";
  fields.summary.value = draft.summary ?? "";
  fields.completed.value = (draft.completed_items ?? []).join("\n");
  fields.next_steps.value = (draft.next_steps ?? []).join("\n");
  fields.risks.value = (draft.risks ?? []).join("\n");

  // textContent, never innerHTML: a review note is model output and stays
  // data, exactly as user text does elsewhere.
  const notes = body.review_notes ?? [];
  notesList.replaceChildren(
    ...notes.map((note) => {
      const item = document.createElement("li");
      item.textContent = note;
      return item;
    }),
  );
  notesBlock.hidden = notes.length === 0;

  showMetrics(body.metrics);

  // The status is left unchosen on purpose, so confirming is a decision.
  statusSelect.value = "";
  draftFromImage = fromImage;
  listedFigures = [];
  refreshFigures();
  draftSection.hidden = false;
  fields.title.focus();
}

/** Map the documented error envelope to one sentence the user can act on. */
async function messageFor(response) {
  try {
    const body = await response.json();
    if (body?.error?.message) return body.error.message;
  } catch {
    // An error response that is not JSON is still an error; fall through.
  }
  if (response.status === 503) return "AI assistance is turned off.";
  return `The draft could not be generated (HTTP ${response.status}).`;
}

async function generate() {
  const text = source.value.trim();
  if (!text && !notesImage) {
    showError("Paste some project notes or add an image first.");
    source.focus();
    return;
  }

  const request = ++currentRequest;
  const withImage = Boolean(notesImage);
  clearError();
  setBusy(true);

  try {
    const payload = { source_text: text };
    if (withImage) payload.image_data_url = await downscaleToJpeg(notesImage.objectUrl);
    if (request !== currentRequest) return;
    const response = await fetch("/api/ai/extract-progress", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (request !== currentRequest) return; // cancelled or superseded

    if (!response.ok) {
      // The source text is left exactly as typed: a failure must not cost the
      // user their notes (scope §5).
      showError(await messageFor(response));
      return;
    }
    showDraft(await response.json(), { fromImage: withImage });
  } catch {
    if (request !== currentRequest) return;
    showError("Could not reach the service. Your notes are unchanged; try again.");
  } finally {
    if (request === currentRequest) setBusy(false);
  }
}

function confirmDraft() {
  updateCreate();
  if (createButton.disabled) return; // never trust the disabled state alone

  // Born complete: only a structure change rebuilds the list, so a card
  // filled in afterwards would show empty fields until the next rebuild.
  const card = addCard("progress", {
    title: fields.title.value.trim(),
    status: statusSelect.value,
    summary: fields.summary.value.trim(),
    completed: linesToList(fields.completed.value),
    next_steps: linesToList(fields.next_steps.value),
    risks: linesToList(fields.risks.value),
  });
  if (!card) {
    showError("Card limit reached. Delete a card before creating another.");
    return;
  }

  // Ticked metric proposals become ordinary metric cards, in the order they
  // were proposed. Each is created the same way a hand-made one is, so
  // nothing downstream can tell them apart, and an unticked proposal simply
  // never existed.
  let metricsMade = 0;
  for (const { metric, box } of metricProposals) {
    if (!box.checked) continue;
    const made = addCard("metric", {
      title: metric.title,
      current: String(metric.current),
      previous: metric.previous === null || metric.previous === undefined
        ? ""
        : String(metric.previous),
      unit: metric.unit,
      unit_label: metric.unit_label ?? "",
    });
    if (!made) {
      showError("Card limit reached, so not every metric was created.");
      break;
    }
    metricsMade += 1;
  }

  close();
  document.getElementById(`f-${card.id}-title`)?.focus();
  return { card, metricsMade };
}

function close() {
  // Abandon any answer still in flight, then drop the notes and the draft.
  currentRequest += 1;
  setBusy(false);
  clearError();
  hideDraft();
  source.value = "";
  clearNotesImage();
  if (panel.open) panel.close();
}

export function initAiReview({ announce = () => {} } = {}) {
  if (!panel || !openButton) return;

  openButton.addEventListener("click", () => {
    hideDraft();
    clearError();
    panel.showModal();
    source.focus();
  });

  generateButton.addEventListener("click", generate);
  cancelButton.addEventListener("click", () => {
    close();
    announce("AI draft discarded");
  });

  statusSelect.addEventListener("change", updateCreate);
  numbersChecked.addEventListener("change", updateCreate);
  for (const control of Object.values(fields)) control.addEventListener("input", refreshFigures);
  metricsList.addEventListener("change", refreshFigures);

  imageInput.addEventListener("change", () => {
    const file = imageInput.files?.[0];
    if (file) attachNotesImage(file);
  });
  imageRemove.addEventListener("click", () => {
    clearNotesImage();
    imageInput.focus();
  });
  // "Paste notes": an image pasted into the notes is attached, and any
  // text pasted with it still goes into the notes as usual.
  source.addEventListener("paste", (event) => {
    const file = [...(event.clipboardData?.files ?? [])].find((item) =>
      item.type.startsWith("image/"),
    );
    if (!file) return;
    if (!event.clipboardData.getData("text/plain")) event.preventDefault();
    attachNotesImage(file);
  });

  createButton.addEventListener("click", () => {
    const made = confirmDraft();
    if (!made) return;
    announce(
      made.metricsMade
        ? `Progress card and ${made.metricsMade} metric card${made.metricsMade > 1 ? "s" : ""} created from the AI draft`
        : "Card created from AI draft",
    );
  });

  // Esc closes a native dialog; treat it as cancelling.
  panel.addEventListener("close", close);
}
