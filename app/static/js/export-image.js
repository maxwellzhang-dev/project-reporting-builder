// PNG export for a single card (docs/scope.md §6, docs/architecture.md §7).
//
// Three rules shape this module:
//
//   1. The snapshot is isolated. The preview node is cloned into an off-screen
//      container and rendered from there, so the export carries the card and
//      not the editing controls around it, and a later edit cannot change a
//      render already in flight.
//   2. A card that changed or disappeared mid-export produces no file. The
//      revision is checked again after rendering and the result is discarded
//      if it no longer matches.
//   3. Temporary nodes and Object URLs are released on success and on
//      failure alike.
//
// The library is fetched from this origin, never a CDN, and loaded on first
// use so that a session which never exports never pays for it.

const VENDOR_SRC = "/static/vendor/html-to-image.js";
const PIXEL_RATIO = 2; // legible when pasted into a document at 1x

let loading = null;

function loadLibrary() {
  if (window.htmlToImage) return Promise.resolve(window.htmlToImage);
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = VENDOR_SRC;
    script.onload = () =>
      window.htmlToImage
        ? resolve(window.htmlToImage)
        : reject(new Error("export library did not initialise"));
    script.onerror = () => {
      loading = null; // a failed load must not poison later attempts
      reject(new Error("export library could not be loaded"));
    };
    document.head.append(script);
  });
  return loading;
}

function safeFilename(title) {
  const base = (title || "card").trim().replace(/[\\/:*?"<>|]+/g, " ").replace(/\s+/g, "-");
  // Keep it short enough for any filesystem, and never empty.
  return `${base.slice(0, 60) || "card"}.png`;
}

/**
 * Build the off-screen copy that is actually rendered.
 *
 * It is positioned off-screen rather than hidden: a node with `display: none`
 * has no layout, and would render as an empty image. The width is pinned to
 * what the preview currently occupies, and the height left to the content, so
 * nothing is silently cropped.
 */
function stage(previewNode) {
  // Two nodes, not one. The outer node carries the off-screen position and is
  // never captured; the inner node is what gets rendered.
  //
  // This matters more than it looks: the renderer clones the node it is given
  // together with its computed style, so putting `position: fixed; left:
  // -10000px` on the captured node pushes the content outside the canvas and
  // produces a blank image that still has the right dimensions. Test plan §8
  // is right that decoding a file proves nothing about what is in it.
  const outer = document.createElement("div");
  outer.setAttribute("aria-hidden", "true");
  outer.style.cssText = "position:fixed;left:-10000px;top:0;";

  const target = document.createElement("div");
  // box-sizing is border-box across this stylesheet, which would subtract the
  // padding from the width and render the clone narrower than the original,
  // rewrapping its text. content-box keeps the copy the width it really is.
  target.style.cssText =
    "padding:16px;box-sizing:content-box;" +
    `width:${Math.ceil(previewNode.getBoundingClientRect().width)}px;`;

  // The preview's own background, so the PNG is never transparent-on-unknown.
  const background = getComputedStyle(previewNode).backgroundColor;
  target.style.background =
    background && background !== "rgba(0, 0, 0, 0)" ? background : "#ffffff";

  const copy = previewNode.cloneNode(true);
  copy.style.maxHeight = "none";
  copy.style.overflow = "visible";
  target.append(copy);
  outer.append(target);
  document.body.append(outer);
  return { outer, target };
}

/**
 * Save a Blob, through an Object URL rather than a `data:` URL.
 *
 * A 2x PNG easily runs to several megabytes, and a `data:` URL that long is
 * unreliable to download: the browser can report success and write no file.
 * The URL is revoked once the click has been dispatched, which is also what
 * docs/architecture.md §7 requires.
 */
function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  try {
    link.click();
  } finally {
    link.remove();
    // Revoked on a later tick: revoking synchronously can cancel the download
    // the click just started.
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  }
}

/**
 * Export one card's preview as a PNG.
 *
 * `stillCurrent()` is asked again after rendering and must return false if the
 * card was edited or deleted while the export was running.
 *
 * Resolves to "downloaded" or "stale", and rejects only when the render
 * itself failed, which the caller reports and the user can retry.
 */
export async function exportCardPng(previewNode, { title, stillCurrent = () => true }) {
  if (!previewNode) throw new Error("nothing to export");

  const library = await loadLibrary();
  const { outer, target } = stage(previewNode);
  try {
    const blob = await library.toBlob(target, {
      pixelRatio: PIXEL_RATIO,
      cacheBust: true,
    });
    if (!blob) throw new Error("the image came back empty");
    // Checked after the render, not before: the point is to catch a change
    // that happened while it was running.
    if (!stillCurrent()) return "stale";
    download(blob, safeFilename(title));
    return "downloaded";
  } finally {
    outer.remove();
  }
}
