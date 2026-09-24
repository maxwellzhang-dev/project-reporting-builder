// Wires the page together: toolbar, card list, deletion dialog, status line.

import { initAiReview } from "./ai-review.js";
import { initImageDescribe } from "./image-describe.js";
import { copyCard, setManualFallback } from "./clipboard.js";
import { ReportIncomplete, reportHtml, reportText } from "./export-report.js";
import { buildCardEditor, setDeletionConfirmer } from "./editor.js";
import { Persistence, SaveState } from "./persistence.js";
import { cancelPreview } from "./preview.js";
import {
  clearSelection,
  isSelected,
  onSelectionChange,
  prune,
  selectOnly,
  selectedCount,
} from "./selection.js";
import {
  addCard,
  clearAll,
  getBlobs,
  getCards,
  MAX_CARDS,
  removeCards,
  replaceAll,
  subscribe,
} from "./state.js";

const list = document.getElementById("card-list");
const empty = document.getElementById("empty-state");
const status = document.getElementById("app-status");
const counter = document.getElementById("card-count");
const addButtons = [...document.querySelectorAll("[data-add-card]")];
const dialog = document.getElementById("confirm-delete");
const dialogText = document.getElementById("confirm-delete-text");
const dialogTitle = document.getElementById("confirm-delete-title");
const dialogAction = document.getElementById("confirm-delete-action");
const saveState = document.getElementById("save-state");
const clearButton = document.getElementById("clear-local-data");
// Declared up here: render() runs on the first restore, before the selection
// section below is reached, and a const read before its line throws.
const scope = document.getElementById("report-scope");
const selectAllButton = document.getElementById("select-all");
const clearSelectionButton = document.getElementById("clear-selection");
const deleteSelectedButton = document.getElementById("delete-selected");
const exportButtons = ["copy-report", "download-report", "print-report"].map((id) =>
  document.getElementById(id),
);

function announce(message) {
  status.textContent = message;
}

/**
 * Ask before anything that cannot be undone: one card, several, or the whole
 * local draft. One native <dialog>, which traps focus and restores it on
 * close; only its words change.
 */
function confirmAction({ title, text, action }) {
  return new Promise((resolve) => {
    if (!dialog?.showModal) {
      resolve(true);
      return;
    }
    dialogTitle.textContent = title;
    dialogText.textContent = text;
    dialogAction.textContent = action;
    dialog.returnValue = "cancel";
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "delete"), {
      once: true,
    });
    dialog.showModal();
  });
}

setDeletionConfirmer(async (name) => {
  const confirmed = await confirmAction({
    title: "Delete card",
    text: `Delete this ${name.toLowerCase()}? This cannot be undone.`,
    action: "Delete",
  });
  announce(confirmed ? `${name} deleted` : "Deletion cancelled");
  return confirmed;
});

function focusAfterRemoval(previousIds) {
  const remaining = getCards().map((card) => card.id);
  const removedIndex = previousIds.findIndex((id) => !remaining.includes(id));
  if (removedIndex === -1) return;
  const neighbour = remaining[Math.min(removedIndex, remaining.length - 1)];
  // Skip disabled controls: "Move up" is disabled on the first card, and a
  // disabled element cannot take focus, which would drop it to the body.
  const focusable = "button:not([disabled]), input, select, textarea";
  const target = neighbour
    ? list.querySelector(`[data-card-id="${neighbour}"] :is(${focusable})`)
    : addButtons[0];
  // A closing <dialog> restores focus to its opener, which no longer exists.
  // Take focus after that has happened rather than before.
  requestAnimationFrame(() => target?.focus());
}

let knownIds = [];

function render(cards, kind) {
  if (kind !== "structure") return; // field edits redraw their own preview
  prune(cards.map((card) => card.id)); // a deleted card cannot stay selected
  const activeId = document.activeElement?.id;
  const editors = cards.map((card) => buildCardEditor(card, { announce, onChanged: () => {} }));
  list.replaceChildren(...editors);

  // The whole list is rebuilt on every structural change, so only a card that
  // was not there before gets the entrance animation, and the page scrolls to
  // it. On first load every card is new, which gives a staggered reveal.
  const added = editors.filter((node) => !knownIds.includes(node.dataset.cardId));
  added.forEach((node, index) => {
    node.classList.add("is-new");
    node.style.setProperty("--stagger", `${Math.min(index, 8) * 40}ms`);
  });
  if (knownIds.length && added.length === 1) {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    added[0].scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "nearest" });
  }

  empty.hidden = cards.length > 0;
  showSelection();
  counter.textContent = `${cards.length} of ${MAX_CARDS} cards`;
  for (const button of addButtons) button.disabled = cards.length >= MAX_CARDS;

  if (cards.length < knownIds.length) focusAfterRemoval(knownIds);
  else if (activeId) document.getElementById(activeId)?.focus();
  knownIds = cards.map((card) => card.id);
}

for (const button of addButtons) {
  button.addEventListener("click", () => {
    const card = addCard(button.dataset.addCard);
    if (!card) {
      announce(`Card limit reached: ${MAX_CARDS} cards`);
      return;
    }
    announce(`${button.textContent.replace("Add ", "")} added`);
    document.getElementById(`f-${card.id}-title`)?.focus();
  });
}

subscribe(render);

initAiReview({ announce });
initImageDescribe({ announce });

// The manual copy route, for every browser that refuses the Clipboard API.
const manualCopy = document.getElementById("manual-copy");
const manualCopyText = document.getElementById("manual-copy-text");
setManualFallback((text) => {
  manualCopyText.value = text;
  if (manualCopy?.showModal) {
    manualCopy.showModal();
    manualCopyText.focus();
    manualCopyText.select();
  }
  announce("Copy it by hand: this browser would not let the page use the clipboard.");
});
document.getElementById("manual-copy-close")?.addEventListener("click", () => manualCopy.close());

/* ---- whole-report sharing (milestone 7) ---- */

/** Turn a refusal into a sentence that names the cards holding it up. */
function reportProblem(error) {
  if (error instanceof ReportIncomplete) {
    return `The report could not be built: ${error.titles.join(", ")} still needs attention.`;
  }
  return "The report could not be built. Your cards are unchanged; try again.";
}


/* ---- selection: batch copy, download, print and delete ---- */


/** The cards an export applies to: exactly the selection, in report order. */
function targetCards() {
  return getCards().filter((card) => isSelected(card.id));
}


/** Exports need a selection; say so rather than exporting something unasked. */
function guardSelection() {
  if (selectedCount()) return false;
  announce(getCards().length ? "Select the cards to export first." : "There are no cards yet.");
  return true;
}

function plural(count, word = "card") {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/** Bring the bar, the checkboxes and the card highlights in line with the selection. */
function showSelection() {
  const count = selectedCount();
  const total = getCards().length;
  scope.textContent = count
    ? `${count} of ${total} selected`
    : total
      ? "Select cards to export"
      : "No cards yet";
  for (const button of exportButtons) button.disabled = !count;
  clearSelectionButton.hidden = !count;
  deleteSelectedButton.hidden = !count;
  selectAllButton.hidden = !total || count === total;
  for (const node of list.querySelectorAll(".editor-card")) {
    const on = isSelected(node.dataset.cardId);
    node.classList.toggle("is-selected", on);
    const box = node.querySelector(".editor-card__title input[type=checkbox]");
    if (box) box.checked = on;
  }
}

onSelectionChange(showSelection);

selectAllButton?.addEventListener("click", () => {
  selectOnly(getCards().map((card) => card.id));
  announce(`${plural(getCards().length)} selected`);
});

clearSelectionButton?.addEventListener("click", () => {
  clearSelection();
  announce("Selection cleared");
  selectAllButton.focus();
});

deleteSelectedButton?.addEventListener("click", async () => {
  const doomed = targetCards();
  if (!selectedCount() || !doomed.length) return;
  const confirmed = await confirmAction({
    title: `Delete ${plural(doomed.length)}`,
    text: `Delete the ${plural(doomed.length, "selected card")}? This cannot be undone.`,
    action: "Delete",
  });
  if (!confirmed) {
    announce("Deletion cancelled");
    return;
  }
  for (const card of doomed) cancelPreview(card.id);
  const count = removeCards(doomed.map((card) => card.id));
  announce(`${plural(count)} deleted`);
  requestAnimationFrame(() => (list.querySelector(".editor-card input") ?? addButtons[0])?.focus());
});

document.getElementById("copy-report")?.addEventListener("click", async () => {
  if (guardSelection()) return;
  try {
    const cards = targetCards();
    const text = await reportText(cards);
    // Reuses the per-card clipboard path, so the manual fallback and the
    // permission handling are the same ones already tested.
    const outcome = await copyCard({ plain_text: text });
    if (outcome === "copied") {
      announce(`${plural(cards.length)} copied`);
    }
  } catch (error) {
    announce(reportProblem(error));
  }
});

document.getElementById("download-report")?.addEventListener("click", async () => {
  if (guardSelection()) return;
  let url;
  try {
    const cards = targetCards();
    const html = await reportHtml(document.title, cards);
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "project-report.html";
    document.body.append(link);
    link.click();
    link.remove();
    announce(`${plural(cards.length)} downloaded`);
  } catch (error) {
    announce(reportProblem(error));
  } finally {
    if (url) setTimeout(() => URL.revokeObjectURL(url), 30_000);
  }
});

document.getElementById("print-report")?.addEventListener("click", () => {
  if (guardSelection()) return;
  // The print stylesheet does the work; this only opens the dialog, where
  // the browser's own "Save as PDF" lives. With a selection, the other cards
  // are marked so print leaves them out, and unmarked once printing ends.
  const excluded = [...list.querySelectorAll(".editor-card")].filter(
    (node) => !isSelected(node.dataset.cardId),
  );
  for (const node of excluded) node.classList.add("is-print-excluded");
  const restore = () => {
    for (const node of excluded) node.classList.remove("is-print-excluded");
  };
  window.addEventListener("afterprint", restore, { once: true });
  window.print();
  setTimeout(restore, 0); // print() blocks where the dialog is modal; afterprint may never fire
});

// Health check stays from milestone 1: it is the only signal that the API is up.
(async () => {
  const target = document.getElementById("service-status");
  try {
    const response = await fetch("/healthz");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    target.textContent = `Service status: ${(await response.json()).status}`;
  } catch {
    target.textContent = "Service status: unavailable";
  }
})();


/* ---- local draft persistence (milestone 4) ---- */

const SAVE_LABELS = {
  [SaveState.IDLE]: "",
  [SaveState.SAVING]: "Saving…",
  [SaveState.SAVED]: "Saved locally",
  [SaveState.FAILED]: "Save failed — your work is still on screen",
};

const store = new Persistence((state, error) => {
  saveState.textContent = SAVE_LABELS[state] ?? "";
  saveState.dataset.state = state;
  if (error) console.warn("draft save failed", error);
});

let saveTimer;
function scheduleSave() {
  clearTimeout(saveTimer);
  // Report the change as unsaved straight away. Waiting for the debounce left
  // "Saved locally" on screen for 400 ms after an edit that had not been
  // written, and a reload in that window lost the edit while claiming it was
  // safe.
  store.onStateChange(SaveState.SAVING);
  saveTimer = setTimeout(() => {
    store.save(getCards(), null, getBlobs());
  }, 400);
}

subscribe(() => scheduleSave());

clearButton?.addEventListener("click", async () => {
  if (getCards().length) {
    const confirmed = await confirmAction({
      title: "Clear local data",
      text: `Delete all ${plural(getCards().length)} and the draft saved in this browser? This cannot be undone.`,
      action: "Clear all",
    });
    if (!confirmed) {
      announce("Nothing was cleared");
      return;
    }
  }
  clearTimeout(saveTimer); // a pending autosave must not recreate the draft
  try {
    await store.clear();
    clearAll();
    announce("Local draft cleared");
  } catch {
    announce("Could not clear the local draft");
  }
});

(async () => {
  try {
    await store.open();
    const restored = await store.restore();
    if (restored?.cards?.length) {
      replaceAll(restored.cards, restored.blobs);
      announce(`Draft restored from ${new Date(restored.savedAt).toLocaleString()}`);
    }
  } catch (error) {
    // Corrupt or unsupported data is reported, never silently dropped.
    saveState.textContent = error.recoverable
      ? "A saved draft could not be read. Use Clear local data to start fresh."
      : "Local draft storage is unavailable; your work will not be saved.";
    saveState.dataset.state = SaveState.FAILED;
  }
})();
