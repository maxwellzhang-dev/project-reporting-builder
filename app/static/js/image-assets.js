// Image files are not uploaded (docs/scope.md §7). The exceptions are the
// downscaled copies sent when the user asks AI to read an image, from an
// image card (image-describe.js) or with notes (ai-review.js). This module validates
// one and hands back metadata plus an Object URL for the preview.

export const MAX_BYTES = 5 * 1024 * 1024;
export const MAX_SIDE = 4096;
export const MAX_PIXELS = 12_000_000;
const ACCEPTED = ["image/png", "image/jpeg", "image/webp"];

export class ImageRejected extends Error {}

function measure(objectUrl) {
  return new Promise((resolve, reject) => {
    const probe = new Image();
    probe.onload = () => resolve({ width: probe.naturalWidth, height: probe.naturalHeight });
    probe.onerror = () => reject(new ImageRejected("That file could not be read as an image."));
    probe.src = objectUrl;
  });
}

/** Validate a picked file. Throws ImageRejected; the caller keeps any existing image. */
export async function acceptImage(file) {
  if (!ACCEPTED.includes(file.type)) {
    throw new ImageRejected("Use a PNG, JPEG or WebP file.");
  }
  if (file.size > MAX_BYTES) {
    throw new ImageRejected("That file is over the 5 MB limit.");
  }

  const objectUrl = URL.createObjectURL(file);
  let size;
  try {
    size = await measure(objectUrl);
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    throw error;
  }

  if (size.width > MAX_SIDE || size.height > MAX_SIDE || size.width * size.height > MAX_PIXELS) {
    URL.revokeObjectURL(objectUrl);
    throw new ImageRejected("That image is too large: 4096px per side, 12 megapixels total.");
  }

  return { name: file.name, type: file.type, bytes: file.size, objectUrl, ...size };
}
