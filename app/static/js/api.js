// Talks to POST /api/cards/render and drops answers that no longer apply.
//
// A response is applied only when the card still exists and its revision has
// not moved on. Without that, a slow reply for an old edit could overwrite a
// newer preview, or a deleted card could reappear (docs/test_plan.md §5).

import { getCard } from "./state.js";

/** Strip editor-only fields and coerce the shapes the API expects. */
function toPayload(card) {
  const common = { id: card.id, type: card.type, title: card.title.trim() };
  if (card.type === "progress") {
    return {
      ...common,
      status: card.status,
      summary: card.summary.trim(),
      completed: card.completed.filter((item) => item.trim()),
      next_steps: card.next_steps.filter((item) => item.trim()),
      risks: card.risks.filter((item) => item.trim()),
    };
  }
  if (card.type === "metric") {
    return {
      ...common,
      current: card.current === "" ? null : Number(card.current),
      previous: card.previous === "" ? null : Number(card.previous),
      unit: card.unit,
      unit_label: card.unit_label.trim(),
      note: card.note.trim(),
    };
  }
  return { ...common, alt_text: card.alt_text.trim(), caption: card.caption.trim() };
}

export class RenderError extends Error {
  constructor(message, fieldErrors = {}) {
    super(message);
    this.fieldErrors = fieldErrors;
  }
}

/** Map the documented error envelope to { fieldName: message }. */
function fieldErrorsFrom(body) {
  const errors = {};
  for (const field of body?.error?.fields ?? []) {
    const name = String(field.path).split(".").pop();
    errors[name] = field.message ?? "Invalid value";
  }
  return errors;
}

export async function renderCard(card) {
  const revision = card.revision;
  const response = await fetch("/api/cards/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ revision, card: toPayload(card) }),
  });

  const current = getCard(card.id);
  if (!current || current.revision !== revision) return null; // superseded or deleted

  if (response.status === 422) {
    const body = await response.json();
    throw new RenderError(body?.error?.message ?? "Some fields need attention",
                          fieldErrorsFrom(body));
  }
  if (!response.ok) throw new RenderError(`Preview failed (HTTP ${response.status})`);

  const body = await response.json();
  if (body.card_id !== card.id || body.revision !== revision) return null;
  return body;
}
