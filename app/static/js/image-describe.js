// Drafting alternative text and a caption for an image card, with AI.
//
// Images otherwise never leave the browser (docs/scope.md §7), so this is the
// one exception and it is opt-in every time:
//
//   1. Nothing is sent until the person has seen the image and pressed Send.
//      Opening the panel sends nothing; cancelling sends nothing.
//   2. What is sent is a downscaled JPEG copy, not the original file. The
//      original stays in IndexedDB as before.
//   3. The draft lives in this module only, like the notes draft in
//      ai-review.js: it never enters the report state, so persistence cannot
//      write it. It reaches the card only through "Use this text", which fills
//      the card's own fields and lets their normal validation apply.
//   4. Every response carries the request number that asked for it; a reply
//      to a cancelled or superseded request is dropped.
//   5. Every figure in the draft is listed for the person to check, and
//      "Use this text" waits until they say they have. On small print the
//      live model misread digits (1644 as 1464, then as 1044) while
//      reporting nothing uncertain, so its own review notes cannot be the
//      safeguard. The list is extracted here, by the page, not by the model.

import { getCard } from "./state.js";

// Enough to read a dashboard or a chart label, small enough to stay well
// under the 1 MiB the API accepts.
const MAX_SIDE = 1024;
const JPEG_QUALITY = 0.85;

const panel = document.getElementById("image-ai");
const thumb = document.getElementById("image-ai-thumb");
const sendButton = document.getElementById("image-ai-send");
const cancelButton = document.getElementById("image-ai-cancel");
const startActions = document.getElementById("image-ai-start-actions");
const errorLine = document.getElementById("image-ai-error");
const busyLine = document.getElementById("image-ai-busy");
const draftSection = document.getElementById("image-ai-draft");
const altDraft = document.getElementById("image-ai-alt");
const captionDraft = document.getElementById("image-ai-caption");
const notesBlock = document.getElementById("image-ai-notes-block");
const notesList = document.getElementById("image-ai-notes");
const useButton = document.getElementById("image-ai-use");
const numbersBlock = document.getElementById("image-ai-numbers-block");
const numbersList = document.getElementById("image-ai-numbers");
const numbersChecked = document.getElementById("image-ai-numbers-checked");

// A figure as it would appear in a report: an optional sign or currency, the
// digits with any separators, and a short unit such as %, k or ms.
const FIGURE = /(?<![A-Za-z0-9.])[+\-−]?[$€£¥]?\d(?:[\d,.]*\d)?(?:\s?(?:%|pp|k|m|bn|ms|s|x)\b|%)?/gi;

let cardId = null;
let currentRequest = 0;
let announce = () => {};

/** Every distinct figure in the text, in order of first appearance. */
export function figuresIn(text) {
  const seen = new Set();
  for (const match of text.matchAll(FIGURE)) seen.add(match[0].trim());
  return [...seen];
}

let listedFigures = [];

/** List the draft's figures; a changed list has to be checked again. */
function refreshFigures() {
  const figures = figuresIn(`${altDraft.value}\n${captionDraft.value}`);
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
  useButton.disabled = figures.length > 0 && !numbersChecked.checked;
}

/** A JPEG data URL of the image, longest side at most MAX_SIDE. */
export async function downscaleToJpeg(src, maxSide = MAX_SIDE) {
  const image = new Image();
  image.src = src;
  await image.decode();
  const scale = Math.min(1, maxSide / Math.max(image.naturalWidth, image.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
  const context = canvas.getContext("2d");
  // JPEG has no transparency; a transparent PNG would otherwise turn black.
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", JPEG_QUALITY);
}

function showError(message) {
  errorLine.textContent = message;
  errorLine.hidden = false;
}

function clearError() {
  errorLine.textContent = "";
  errorLine.hidden = true;
}

function setBusy(busy) {
  sendButton.disabled = busy;
  sendButton.setAttribute("aria-busy", String(busy));
  busyLine.textContent = busy ? "Describing the image…" : "";
}

function reset() {
  currentRequest += 1; // abandon anything in flight
  setBusy(false);
  clearError();
  draftSection.hidden = true;
  startActions.hidden = false;
  altDraft.value = "";
  captionDraft.value = "";
  notesList.replaceChildren();
  notesBlock.hidden = true;
  listedFigures = [];
  numbersList.replaceChildren();
  numbersChecked.checked = false;
  numbersBlock.hidden = true;
  useButton.disabled = false;
}

async function messageFor(response) {
  try {
    const body = await response.json();
    if (body?.error?.message) return body.error.message;
  } catch {
    // An error response that is not JSON is still an error; fall through.
  }
  if (response.status === 503) return "AI assistance is turned off.";
  return `The image could not be described (HTTP ${response.status}).`;
}

function showDraft(body) {
  altDraft.value = body.draft?.alt_text ?? "";
  captionDraft.value = body.draft?.caption ?? "";
  // textContent, never innerHTML: review notes are model output.
  const notes = body.review_notes ?? [];
  notesList.replaceChildren(
    ...notes.map((note) => {
      const item = document.createElement("li");
      item.textContent = note;
      return item;
    }),
  );
  notesBlock.hidden = notes.length === 0;
  refreshFigures();
  startActions.hidden = true;
  draftSection.hidden = false;
  altDraft.focus();
}

async function send() {
  const card = getCard(cardId);
  if (!card?.image?.objectUrl) {
    showError("Add an image to this card first.");
    return;
  }

  const request = ++currentRequest;
  clearError();
  setBusy(true);
  try {
    const imageDataUrl = await downscaleToJpeg(card.image.objectUrl);
    if (request !== currentRequest) return;
    const response = await fetch("/api/ai/describe-image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_data_url: imageDataUrl }),
    });
    if (request !== currentRequest) return; // cancelled or superseded

    if (!response.ok) {
      showError(await messageFor(response));
      return;
    }
    showDraft(await response.json());
    announce("Image description drafted for review");
  } catch {
    if (request !== currentRequest) return;
    showError("Could not reach the service. Your card is unchanged; try again.");
  } finally {
    if (request === currentRequest) setBusy(false);
  }
}

/** Put the reviewed draft into the card's own fields, as if typed. */
function useDraft() {
  if (listedFigures.length && !numbersChecked.checked) return; // never trust the disabled state alone
  if (!getCard(cardId)) {
    close();
    announce("That card was deleted, so the description was not used");
    return;
  }
  const targetId = cardId;
  for (const [name, value] of [
    ["alt_text", altDraft.value.trim()],
    ["caption", captionDraft.value.trim()],
  ]) {
    const control = document.getElementById(`f-${targetId}-${name}`);
    if (!control) continue;
    control.value = value;
    // The field's own input handler updates state, validation and preview.
    control.dispatchEvent(new Event("input", { bubbles: true }));
  }
  close();
  announce("Alternative text and caption filled in from the AI draft");
  document.getElementById(`f-${targetId}-alt_text`)?.focus();
}

function close() {
  reset();
  thumb.removeAttribute("src");
  cardId = null;
  if (panel.open) panel.close();
}

/** Open the panel for one image card. Sends nothing until the person does. */
export function openImageDescribe(id) {
  const card = getCard(id);
  if (!panel || !card?.image?.objectUrl) return;
  reset();
  cardId = id;
  thumb.src = card.image.objectUrl;
  panel.showModal();
  sendButton.focus();
}

export function initImageDescribe(options = {}) {
  if (!panel) return;
  announce = options.announce ?? announce;
  sendButton.addEventListener("click", send);
  cancelButton.addEventListener("click", () => {
    close();
    announce("Image description cancelled");
  });
  useButton.addEventListener("click", useDraft);
  altDraft.addEventListener("input", refreshFigures);
  captionDraft.addEventListener("input", refreshFigures);
  numbersChecked.addEventListener("change", refreshFigures);
  // Esc closes a native dialog; treat it as cancelling.
  panel.addEventListener("close", () => {
    if (cardId !== null) close();
  });
}
