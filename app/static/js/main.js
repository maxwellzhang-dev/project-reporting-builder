// Wires the page together: toolbar, card list, deletion dialog, status line.

import { initAiReview } from "./ai-review.js";
import { copyCard, setManualFallback } from "./clipboard.js";
import { ReportIncomplete, reportHtml, reportText } from "./export-report.js";
import { buildCardEditor, setDeletionConfirmer } from "./editor.js";
import { Persistence, SaveState } from "./persistence.js";
import { addCard, clearAll, getBlobs, getCards, MAX_CARDS, replaceAll, subscribe } from "./state.js";

const list = document.getElementById("card-list");
const empty = document.getElementById("empty-state");
const status = document.getElementById("app-status");
const counter = document.getElementById("card-count");
const addButtons = [...document.querySelectorAll("[data-add-card]")];
const dialog = document.getElementById("confirm-delete");
const dialogText = document.getElementById("confirm-delete-text");
const saveState = document.getElementById("save-state");
const clearButton = document.getElementById("clear-local-data");

function announce(message) {
  status.textContent = message;
}

// A native <dialog> keeps focus trapped and restores it on close.
setDeletionConfirmer(
  (name) =>
    new Promise((resolve) => {
      if (!dialog?.showModal) {
        resolve(true);
        return;
      }
      dialogText.textContent = `Delete this ${name.toLowerCase()}? This cannot be undone.`;
      dialog.returnValue = "cancel";
      dialog.addEventListener(
        "close",
        () => {
          const confirmed = dialog.returnValue === "delete";
          announce(confirmed ? `${name} deleted` : "Deletion cancelled");
          resolve(confirmed);
        },
        { once: true },
      );
      dialog.showModal();
    }),
);

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

function guardEmpty() {
  if (getCards().length) return false;
  announce("There are no cards to share yet.");
  return true;
}

document.getElementById("copy-report")?.addEventListener("click", async () => {
  if (guardEmpty()) return;
  try {
    const text = await reportText();
    // Reuses the per-card clipboard path, so the manual fallback and the
    // permission handling are the same ones already tested.
    const outcome = await copyCard({ plain_text: text });
    if (outcome === "copied") announce("Report copied");
  } catch (error) {
    announce(reportProblem(error));
  }
});

document.getElementById("download-report")?.addEventListener("click", async () => {
  if (guardEmpty()) return;
  let url;
  try {
    const html = await reportHtml(document.title);
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "project-report.html";
    document.body.append(link);
    link.click();
    link.remove();
    announce("Report downloaded");
  } catch (error) {
    announce(reportProblem(error));
  } finally {
    if (url) setTimeout(() => URL.revokeObjectURL(url), 30_000);
  }
});

document.getElementById("print-report")?.addEventListener("click", () => {
  if (guardEmpty()) return;
  // The print stylesheet does the work; this only opens the dialog, where
  // the browser's own "Save as PDF" lives.
  window.print();
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
