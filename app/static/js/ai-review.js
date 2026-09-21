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

function hideDraft() {
  draftSection.hidden = true;
  for (const control of Object.values(fields)) control.value = "";
  notesList.replaceChildren();
  notesBlock.hidden = true;
  statusSelect.value = "";
  createButton.disabled = true;
}

function linesToList(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, MAX_ITEMS);
}

function showDraft(body) {
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

  // The status is left unchosen on purpose, so confirming is a decision.
  statusSelect.value = "";
  createButton.disabled = true;
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
  if (!text) {
    showError("Paste some project notes first.");
    source.focus();
    return;
  }

  const request = ++currentRequest;
  clearError();
  setBusy(true);

  try {
    const response = await fetch("/api/ai/extract-progress", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_text: text }),
    });

    if (request !== currentRequest) return; // cancelled or superseded

    if (!response.ok) {
      // The source text is left exactly as typed: a failure must not cost the
      // user their notes (scope §5).
      showError(await messageFor(response));
      return;
    }
    showDraft(await response.json());
  } catch {
    if (request !== currentRequest) return;
    showError("Could not reach the service. Your notes are unchanged; try again.");
  } finally {
    if (request === currentRequest) setBusy(false);
  }
}

function confirmDraft() {
  if (!statusSelect.value) return; // the button is disabled, but never trust that alone

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

  close();
  document.getElementById(`f-${card.id}-title`)?.focus();
  return card;
}

function close() {
  // Abandon any answer still in flight, then drop the notes and the draft.
  currentRequest += 1;
  setBusy(false);
  clearError();
  hideDraft();
  source.value = "";
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

  statusSelect.addEventListener("change", () => {
    createButton.disabled = !statusSelect.value;
  });

  createButton.addEventListener("click", () => {
    if (confirmDraft()) announce("Card created from AI draft");
  });

  // Esc closes a native dialog; treat it as cancelling.
  panel.addEventListener("close", close);
}
