// Copying a card as plain text or as simple rich text, with a manual fallback
// for every way the Clipboard API can be unavailable (docs/scope.md §6).
//
// The text copied is whatever the server rendered for the card's current
// revision. Nothing is reassembled here from form fields, so a copy can never
// be a different thing from the preview the user is looking at.

const NO_CLIPBOARD = "no-clipboard";

let fallbackHandler = () => {};

/** The page supplies a dialog; this module only decides when to ask for it. */
export function setManualFallback(handler) {
  fallbackHandler = handler;
}

function clipboard() {
  // Access can throw in a sandboxed frame, not merely be absent.
  try {
    return navigator.clipboard ?? null;
  } catch {
    return null;
  }
}

async function writePlain(text) {
  const api = clipboard();
  if (!api?.writeText) throw new Error(NO_CLIPBOARD);
  await api.writeText(text);
}

async function writeRich(html, text) {
  const api = clipboard();
  // ClipboardItem is missing in some browsers that still have writeText.
  if (!api?.write || typeof ClipboardItem === "undefined") throw new Error(NO_CLIPBOARD);
  await api.write([
    new ClipboardItem({
      // Both flavours, always: a plain-text target must not receive markup
      // (docs/test_plan.md §8).
      "text/html": new Blob([html], { type: "text/html" }),
      "text/plain": new Blob([text], { type: "text/plain" }),
    }),
  ]);
}

/**
 * Copy a card. `rendered` is the render response for the card's current
 * revision; `rich` selects the HTML flavour where the card type has one.
 *
 * Returns "copied" or "fallback". It never throws for a clipboard failure:
 * a refusal and an absent API are the same thing to the user, who needs the
 * text either way.
 */
export async function copyCard(rendered, { rich = false } = {}) {
  const text = rendered?.plain_text ?? "";
  const html = rendered?.rich_html ?? "";
  if (!text) return "fallback";

  try {
    if (rich && html) await writeRich(html, text);
    else await writePlain(text);
    return "copied";
  } catch {
    // Permission refused, API absent, or a browser that rejects the flavour.
    fallbackHandler(text);
    return "fallback";
  }
}
