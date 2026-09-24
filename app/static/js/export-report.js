// The whole report, in one piece (docs/scope.md §6, "Whole report").
//
// Nothing is rendered here. Each card was already rendered by the server, and
// this assembles those results in the order the cards are arranged. That is
// what makes the export impossible to disagree with the previews on screen:
// it is literally the same text and the same markup.
//
// A card that will not render stops the export and is named. Producing a
// document that looks complete while quietly missing a card is the one
// failure that would matter here, so it is the one the code refuses.

import { ensureRendered } from "./preview.js";
import { getCards } from "./state.js";

const SEPARATOR = "\n\n----------------------------------------\n\n";

export class ReportIncomplete extends Error {
  constructor(titles) {
    super("some cards could not be rendered");
    this.titles = titles;
  }
}

function describe(card, index) {
  const title = card.title?.trim();
  return title ? `"${title}"` : `the ${card.type} card in position ${index + 1}`;
}

/**
 * Render every card in order, or explain which ones stopped it.
 *
 * Rendering is sequential on purpose: the render endpoint is debounced and
 * revision-guarded per card, and firing twenty requests at once would race
 * the previews that are already in flight.
 */
async function renderAll() {
  const cards = getCards();
  if (!cards.length) return { cards: [], rendered: [] };

  const rendered = [];
  const failed = [];
  for (const [index, card] of cards.entries()) {
    try {
      const result = await ensureRendered(card);
      if (result) rendered.push({ card, result });
      else failed.push(describe(card, index));
    } catch {
      // A validation failure is the expected case: the card is incomplete.
      failed.push(describe(card, index));
    }
  }
  if (failed.length) throw new ReportIncomplete(failed);
  return { cards, rendered };
}

/** The whole report as plain text, in order. */
export async function reportText() {
  const { rendered } = await renderAll();
  return rendered.map(({ result }) => result.plain_text.trim()).join(SEPARATOR);
}

/**
 * A card's contribution to the HTML document.
 *
 * An image card has no rich form (scope §6) because the image file is not
 * uploaded, so it contributes its description instead of vanishing. The
 * text is escaped: this is a document built from user content.
 */
function htmlBlock({ card, result }) {
  if (result.rich_html) return result.rich_html;

  const wrapper = document.createElement("div");
  wrapper.style.cssText =
    "max-width:640px;padding:14px 16px;border:1px solid #d9d9de;border-radius:12px;" +
    "font-family:-apple-system,Segoe UI,sans-serif;color:#1d1d1f";

  const heading = document.createElement("h3");
  heading.style.cssText = "margin:0 0 6px;font:600 16px/1.35 inherit";
  heading.textContent = card.title?.trim() || "Image";
  wrapper.append(heading);

  for (const [label, value] of [
    ["", card.caption?.trim()],
    ["Image description: ", card.alt_text?.trim()],
  ]) {
    if (!value) continue;
    const line = document.createElement("p");
    line.style.cssText = "margin:2px 0 0;font:400 13px/1.4 inherit;color:#55555c";
    line.textContent = `${label}${value}`;
    wrapper.append(line);
  }

  const note = document.createElement("p");
  note.style.cssText = "margin:6px 0 0;font:400 12px/1.4 inherit;color:#8a8a90";
  note.textContent = "The image file itself is not included: images are not uploaded.";
  wrapper.append(note);

  return wrapper.outerHTML;
}

/** Escape text that goes into the document shell rather than a card. */
function escapeText(value) {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}

export async function reportHtml(title = "Project report") {
  const { rendered } = await renderAll();
  const blocks = rendered.map((entry) => `    ${htmlBlock(entry)}`).join("\n");
  const generated = new Date().toLocaleString();

  // No stylesheet link and no script: every card carries its own inline
  // styles, so the file stays readable with the application unreachable.
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeText(title)}</title>
</head>
<body style="margin:0;padding:24px;background:#f5f5f7;
             font-family:-apple-system,Segoe UI,sans-serif">
  <h1 style="margin:0 0 4px;font:600 22px/1.3 inherit;color:#1d1d1f">${escapeText(title)}</h1>
  <p style="margin:0 0 20px;font:400 13px/1.4 inherit;color:#55555c">Generated ${escapeText(generated)}</p>
  <main style="display:grid;gap:16px">
${blocks}
  </main>
</body>
</html>
`;
}
