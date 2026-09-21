// Owns the preview column: server HTML in, local image attached by DOM.

import { renderCard, RenderError } from "./api.js";
import { getCard } from "./state.js";

const pending = new Map();

// The last render accepted for each card, kept with the revision it describes.
// Sharing reads from here so that a copy is the same thing as the preview on
// screen, rather than something reassembled from the form (docs/scope.md §6).
const rendered = new Map();

function remember(cardId, revision, result) {
  rendered.set(cardId, {
    revision,
    plain_text: result.plain_text,
    rich_html: result.rich_html,
  });
}

export function forgetRendered(cardId) {
  rendered.delete(cardId);
}

/**
 * The render for this card's current revision, fetching one if what we hold
 * is stale. Sharing is only ever allowed for the current valid revision
 * (docs/architecture.md §7), so a pending edit is rendered first rather than
 * copied from an older answer.
 */
export async function ensureRendered(card) {
  const held = rendered.get(card.id);
  if (held && held.revision === card.revision) return held;

  const result = await renderCard(card);
  if (!result) return null; // superseded or deleted while rendering
  remember(card.id, card.revision, result);
  return rendered.get(card.id);
}

/** Insert the local image into the placeholder the server left for it. */
function attachImage(node, card) {
  const slot = node.querySelector("[data-image-slot]");
  if (!slot || !card.image) return;
  const img = document.createElement("img");
  img.src = card.image.objectUrl;
  img.alt = card.alt_text.trim();
  img.className = "card__image";
  slot.replaceWith(img);
}

export function showError(container, message) {
  container.innerHTML = "";
  const p = document.createElement("p");
  p.className = "preview__placeholder";
  p.textContent = message;
  container.append(p);
}

/**
 * Refresh one card's preview. Debounced per card so typing does not queue a
 * request per keystroke, and late answers are dropped by api.renderCard.
 */
export function schedulePreview(card, container, onFieldErrors) {
  clearTimeout(pending.get(card.id));
  pending.set(
    card.id,
    setTimeout(async () => {
      const latest = getCard(card.id);
      if (!latest) return;
      try {
        const result = await renderCard(latest);
        if (!result) return; // superseded or deleted
        if (!getCard(card.id)) return;
        remember(card.id, latest.revision, result);
        container.innerHTML = result.preview_html;
        attachImage(container, getCard(card.id));
        onFieldErrors({});
      } catch (error) {
        if (error instanceof RenderError) {
          onFieldErrors(error.fieldErrors);
          showError(container, error.message);
          return;
        }
        showError(container, "Preview unavailable. Your text is safe; try again.");
      }
    }, 300),
  );
}

export function cancelPreview(cardId) {
  clearTimeout(pending.get(cardId));
  pending.delete(cardId);
  forgetRendered(cardId);
}
