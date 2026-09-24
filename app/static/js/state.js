// The report the user is editing. One module owns it so every other module
// reads the same truth, and every mutation bumps a revision the renderer can
// use to discard stale responses (docs/test_plan.md §5, "Async Consistency").

export const MAX_CARDS = 20;

const listeners = new Set();
let cards = [];
// Image files, kept out of the card objects so nothing can serialise them by
// accident. Persistence reads them from here (docs/scope.md §7).
const blobs = new Map();

export function rememberBlob(cardId, blob) {
  blobs.set(cardId, blob);
}

export function getBlobs() {
  return blobs;
}

// "structure" means the list itself changed: added, removed or reordered.
// "field" means one card's contents changed. The page rebuilds only on the
// former, so typing never replaces the input the user is typing into.
function emit(kind) {
  for (const listener of listeners) listener(cards, kind);
}

export function subscribe(listener) {
  listeners.add(listener);
  listener(cards, "structure");
  return () => listeners.delete(listener);
}

export function getCards() {
  return cards;
}

export function getCard(id) {
  return cards.find((card) => card.id === id) ?? null;
}

function blankCard(type) {
  const base = { id: crypto.randomUUID(), type, title: "", revision: 0 };
  if (type === "progress") {
    return { ...base, status: "in_progress", summary: "", completed: [], next_steps: [], risks: [] };
  }
  if (type === "metric") {
    return { ...base, current: "", previous: "", unit: "number", unit_label: "", note: "" };
  }
  return { ...base, alt_text: "", caption: "", image: null };
}

/**
 * Add a card, optionally with content already in it.
 *
 * `initial` exists for the AI panel: a confirmed draft has to arrive complete,
 * because only a "structure" change rebuilds the list, so filling a blank card
 * afterwards would leave the new fields invisible until the next rebuild. The
 * id, type and revision stay under this module's control whatever is passed.
 */
export function addCard(type, initial = {}) {
  if (cards.length >= MAX_CARDS) return null;
  const blank = blankCard(type);
  const card = { ...blank, ...initial, id: blank.id, type: blank.type, revision: 0 };
  cards = [...cards, card];
  emit("structure");
  return card;
}

export function updateCard(id, changes) {
  cards = cards.map((card) =>
    card.id === id ? { ...card, ...changes, revision: card.revision + 1 } : card,
  );
  emit("field");
  return getCard(id);
}

export function removeCard(id) {
  const index = cards.findIndex((card) => card.id === id);
  if (index === -1) return -1;
  // Release the image before the card goes, so no Object URL outlives its card.
  releaseImage(cards[index]);
  blobs.delete(id);
  cards = cards.filter((card) => card.id !== id);
  emit("structure");
  return index;
}

/** Remove several cards with one structural change, so the list redraws once. */
export function removeCards(ids) {
  const gone = new Set(ids);
  const removed = cards.filter((card) => gone.has(card.id));
  if (!removed.length) return 0;
  for (const card of removed) {
    releaseImage(card);
    blobs.delete(card.id);
  }
  cards = cards.filter((card) => !gone.has(card.id));
  emit("structure");
  return removed.length;
}

export function moveCard(id, offset) {
  const from = cards.findIndex((card) => card.id === id);
  const to = from + offset;
  if (from === -1 || to < 0 || to >= cards.length) return false;
  const next = [...cards];
  [next[from], next[to]] = [next[to], next[from]];
  cards = next;
  emit("structure");
  return true;
}

export function releaseImage(card) {
  if (card?.image?.objectUrl) URL.revokeObjectURL(card.image.objectUrl);
}

export function replaceAll(newCards, newBlobs = new Map()) {
  for (const card of cards) releaseImage(card);
  blobs.clear();
  for (const [key, value] of newBlobs) blobs.set(key, value);
  cards = newCards;
  emit("structure");
}

export function clearAll() {
  replaceAll([], new Map());
}
