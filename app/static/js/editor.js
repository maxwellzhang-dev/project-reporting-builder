// Builds one card's form. Every control is a native element with a real label,
// so keyboard order, focus and screen-reader naming come for free.

import { copyCard } from "./clipboard.js";
import { exportCardPng } from "./export-image.js";
import { acceptImage, ImageRejected } from "./image-assets.js";
import { rememberBlob } from "./state.js";
import { cancelPreview, ensureRendered, schedulePreview } from "./preview.js";
import { getCard, getCards, moveCard, removeCard, updateCard } from "./state.js";

const STATUSES = [
  ["proposed", "Proposed"],
  ["under_review", "Under Review"],
  ["cleared_to_start", "Cleared to Start"],
  ["in_progress", "In Progress"],
  ["completed", "Completed"],
  ["on_hold", "On Hold"],
  ["cancelled", "Cancelled"],
];

const UNITS = [
  ["number", "Number"],
  ["percent", "Percentage"],
  ["custom", "Custom"],
];

function field(card, name, labelText, { type = "text", multiline = false, hint = "" } = {}) {
  const wrap = document.createElement("div");
  wrap.className = "field";

  const id = `f-${card.id}-${name}`;
  const label = document.createElement("label");
  label.htmlFor = id;
  label.textContent = labelText;

  const control = document.createElement(multiline ? "textarea" : "input");
  control.id = id;
  control.name = name;
  control.value = card[name] ?? "";
  if (!multiline) control.type = type;
  if (multiline) control.rows = 3;

  const error = document.createElement("p");
  error.className = "field__error";
  error.id = `${id}-error`;
  error.hidden = true;
  control.setAttribute("aria-describedby", error.id);

  if (hint) {
    const note = document.createElement("p");
    note.className = "field__hint";
    note.id = `${id}-hint`;
    note.textContent = hint;
    control.setAttribute("aria-describedby", `${note.id} ${error.id}`);
    wrap.append(label, control, note, error);
  } else {
    wrap.append(label, control, error);
  }
  return { wrap, control, error, name };
}

function listField(card, name, labelText) {
  const { wrap, control, error } = field(card, name, labelText, {
    multiline: true,
    hint: "One item per line. Up to 8.",
  });
  control.value = (card[name] ?? []).join("\n");
  return { wrap, control, error, name, isList: true };
}

function select(card, name, labelText, options) {
  const wrap = document.createElement("div");
  wrap.className = "field";
  const id = `f-${card.id}-${name}`;
  const label = document.createElement("label");
  label.htmlFor = id;
  label.textContent = labelText;
  const control = document.createElement("select");
  control.id = id;
  control.name = name;
  for (const [value, text] of options) {
    const option = new Option(text, value, false, card[name] === value);
    control.append(option);
  }
  const error = document.createElement("p");
  error.className = "field__error";
  error.id = `${id}-error`;
  error.hidden = true;
  control.setAttribute("aria-describedby", error.id);
  wrap.append(label, control, error);
  return { wrap, control, error, name };
}

function fieldsFor(card) {
  if (card.type === "progress") {
    return [
      field(card, "title", "Title"),
      select(card, "status", "Status", STATUSES),
      field(card, "summary", "Summary", { multiline: true }),
      listField(card, "completed", "Completed"),
      listField(card, "next_steps", "Next steps"),
      listField(card, "risks", "Risks"),
    ];
  }
  if (card.type === "metric") {
    return [
      field(card, "title", "Metric name"),
      field(card, "current", "Current value", { type: "number" }),
      field(card, "previous", "Previous value", {
        type: "number",
        hint: "Leave blank for no comparison.",
      }),
      select(card, "unit", "Unit", UNITS),
      field(card, "unit_label", "Custom unit label"),
      field(card, "note", "Note", { multiline: true }),
    ];
  }
  return [
    field(card, "title", "Title"),
    field(card, "alt_text", "Alternative text", {
      hint: "Describe the image for people who cannot see it. Required.",
    }),
    field(card, "caption", "Caption"),
  ];
}

/** Copy a card, rendering first if the preview on screen is behind the edits. */
async function shareCard(cardId, { rich }, announce) {
  const card = getCard(cardId);
  if (!card) return;
  try {
    const current = await ensureRendered(card);
    if (!current) return; // the card changed again or went away
    const outcome = await copyCard(current, { rich });
    if (outcome === "copied") announce(rich ? "Rich text copied" : "Text copied");
  } catch {
    announce("Could not prepare this card to copy. Your work is unchanged.");
  }
}

/**
 * Export a card as PNG. The button is disabled while it runs so a second
 * click cannot start a competing export, and the card's revision is captured
 * up front so a render that finishes after an edit is discarded rather than
 * downloaded (docs/architecture.md §7).
 */
async function downloadCard(cardId, preview, button, announce) {
  const card = getCard(cardId);
  if (!card) return;
  const previewNode = preview.querySelector(".card");
  if (!previewNode) {
    announce("There is nothing to export yet. Wait for the preview.");
    return;
  }

  const revision = card.revision;
  const stillCurrent = () => {
    const now = getCard(cardId);
    return Boolean(now) && now.revision === revision;
  };

  button.disabled = true;
  announce("Preparing the image…");
  try {
    const outcome = await exportCardPng(previewNode, { title: card.title, stillCurrent });
    announce(
      outcome === "downloaded"
        ? "Image downloaded. Add a text description when you share it."
        : "The card changed while the image was being made. Try again.",
    );
  } catch {
    announce("The image could not be created. Your card is unchanged; try again.");
  } finally {
    button.disabled = false;
  }
}

export function buildCardEditor(card, { announce, onChanged }) {
  const article = document.createElement("article");
  article.className = "editor-card";
  article.dataset.cardId = card.id;

  const heading = document.createElement("h3");
  heading.className = "editor-card__heading";
  heading.id = `f-${card.id}-heading`;
  heading.textContent = { progress: "Progress card", metric: "Metric card", image: "Image card" }[
    card.type
  ];
  article.setAttribute("aria-labelledby", heading.id);

  const controls = document.createElement("div");
  controls.className = "editor-card__controls";

  const makeButton = (label, handler, className = "") => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.className = className;
    button.addEventListener("click", handler);
    return button;
  };

  const index = getCards().findIndex((item) => item.id === card.id);
  const up = makeButton("Move up", () => {
    if (moveCard(card.id, -1)) announce(`${heading.textContent} moved up`);
  });
  const down = makeButton("Move down", () => {
    if (moveCard(card.id, 1)) announce(`${heading.textContent} moved down`);
  });
  up.disabled = index === 0;
  down.disabled = index === getCards().length - 1;

  const remove = makeButton("Delete", () => onDelete(card, heading.textContent), "danger");
  controls.append(up, down, remove);

  const preview = document.createElement("div");
  preview.className = "preview__body";
  preview.dataset.previewFor = card.id;

  // Sharing (docs/scope.md §6). An image card has a plain-text form but no
  // rich-text one, so it gets no rich button rather than a disabled one.
  const share = document.createElement("div");
  share.className = "editor-card__share";
  const copyText = makeButton("Copy text", () => shareCard(card.id, { rich: false }, announce));
  share.append(copyText);
  if (card.type !== "image") {
    share.append(makeButton("Copy rich", () => shareCard(card.id, { rich: true }, announce)));
  }
  share.append(
    makeButton("Download PNG", (event) =>
      downloadCard(card.id, preview, event.currentTarget, announce),
    ),
  );

  const form = document.createElement("form");
  form.className = "editor-card__form";
  form.addEventListener("submit", (event) => event.preventDefault());

  const fields = fieldsFor(card);
  const applyFieldErrors = (errors) => {
    for (const entry of fields) {
      const message = errors[entry.name];
      entry.error.hidden = !message;
      entry.error.textContent = message ?? "";
      entry.control.setAttribute("aria-invalid", message ? "true" : "false");
    }
  };

  for (const entry of fields) {
    entry.control.addEventListener("input", () => {
      const value = entry.isList
        ? entry.control.value.split("\n").map((line) => line.trim())
        : entry.control.value;
      const updated = updateCard(card.id, { [entry.name]: value });
      if (updated) schedulePreview(updated, preview, applyFieldErrors);
      onChanged();
    });
    form.append(entry.wrap);
  }

  if (card.type === "image") {
    form.append(buildImagePicker(card, preview, applyFieldErrors, announce));
  }

  article.append(heading, controls, form, preview, share);
  schedulePreview(card, preview, applyFieldErrors);
  return article;
}

function buildImagePicker(card, preview, applyFieldErrors, announce) {
  const wrap = document.createElement("div");
  wrap.className = "field";
  const id = `f-${card.id}-image`;
  const label = document.createElement("label");
  label.htmlFor = id;
  label.textContent = "Image file";
  const input = document.createElement("input");
  input.type = "file";
  input.id = id;
  input.accept = "image/png,image/jpeg,image/webp";
  const error = document.createElement("p");
  error.className = "field__error";
  error.hidden = true;

  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    if (!file) return;
    try {
      const image = await acceptImage(file);
      const previous = card.image;
      rememberBlob(card.id, file);
      const updated = updateCard(card.id, { image });
      if (previous?.objectUrl) URL.revokeObjectURL(previous.objectUrl);
      error.hidden = true;
      announce("Image added");
      if (updated) schedulePreview(updated, preview, applyFieldErrors);
    } catch (rejection) {
      // The existing image survives a failed replacement (docs/scope.md §4).
      error.hidden = false;
      error.textContent =
        rejection instanceof ImageRejected ? rejection.message : "That file could not be used.";
      input.value = "";
      announce("Image rejected");
    }
  });

  wrap.append(label, input, error);
  return wrap;
}

let confirmDeletion = async () => true;
export function setDeletionConfirmer(fn) {
  confirmDeletion = fn;
}

async function onDelete(card, name) {
  if (!(await confirmDeletion(name))) return;
  cancelPreview(card.id);
  removeCard(card.id);
}
