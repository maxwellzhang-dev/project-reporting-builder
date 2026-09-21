// One working report in IndexedDB: text in `reports`, image blobs in `assets`.
//
// Rules that shape this module (docs/architecture.md §8, docs/test_plan.md §6):
//   - writes are serialised, so a slow save cannot overwrite newer state
//   - "Saved" is reported only after the transaction completes
//   - a failed save never discards what is in memory
//   - Object URLs are never persisted; new ones are made on restore
//   - deleting a card deletes its image in the same transaction

const DB_NAME = "project-reporting-builder";
const DB_VERSION = 1;
const SCHEMA_VERSION = 1;
const REPORT_KEY = "current";

export const SaveState = { IDLE: "idle", SAVING: "saving", SAVED: "saved", FAILED: "failed" };

function openDatabase() {
  return new Promise((resolve, reject) => {
    if (!globalThis.indexedDB) {
      reject(new Error("This browser has no IndexedDB, so drafts cannot be saved."));
      return;
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains("reports")) db.createObjectStore("reports");
      if (!db.objectStoreNames.contains("assets")) db.createObjectStore("assets");
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB unavailable"));
  });
}

function runTransaction(db, mode, work) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(["reports", "assets"], mode);
    let result;
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error ?? new Error("transaction failed"));
    tx.onabort = () => reject(tx.error ?? new Error("transaction aborted"));
    try {
      result = work(tx.objectStore("reports"), tx.objectStore("assets"));
    } catch (error) {
      tx.abort();
      reject(error);
    }
  });
}

/** Strip anything that must not be persisted: Object URLs, blobs, render state. */
function toStoredCard(card) {
  const { image, ...rest } = card;
  return image ? { ...rest, image: { name: image.name, type: image.type,
    bytes: image.bytes, width: image.width, height: image.height } } : rest;
}

export class Persistence {
  constructor(onStateChange) {
    this.onStateChange = onStateChange;
    this.queue = Promise.resolve();
    this.db = null;
  }

  async open() {
    this.db = await openDatabase();
    return this;
  }

  /** Queue a save. Serialising here is what stops an older write landing last. */
  save(cards, selectedCardId, blobsByCardId) {
    this.onStateChange(SaveState.SAVING);
    this.queue = this.queue
      .then(() => this.#write(cards, selectedCardId, blobsByCardId))
      .then(() => this.onStateChange(SaveState.SAVED))
      .catch((error) => {
        // In-memory content is untouched; only the save failed.
        this.onStateChange(SaveState.FAILED, error);
      });
    return this.queue;
  }

  async #write(cards, selectedCardId, blobsByCardId) {
    if (!this.db) await this.open();
    const keep = new Set(cards.filter((card) => card.image).map((card) => card.id));
    await runTransaction(this.db, "readwrite", (reports, assets) => {
      reports.put(
        {
          schemaVersion: SCHEMA_VERSION,
          savedAt: new Date().toISOString(),
          selectedCardId,
          cards: cards.map(toStoredCard),
        },
        REPORT_KEY,
      );
      for (const [cardId, blob] of blobsByCardId) {
        if (keep.has(cardId)) assets.put(blob, cardId);
      }
      // A deleted card takes its image with it, in the same transaction.
      const stale = assets.getAllKeys();
      stale.onsuccess = () => {
        for (const key of stale.result) if (!keep.has(key)) assets.delete(key);
      };
    });
  }

  /** Restore the saved report, rebuilding Object URLs. Returns null when empty. */
  async restore() {
    if (!this.db) await this.open();
    const stored = await runTransaction(this.db, "readonly", (reports) => {
      const request = reports.get(REPORT_KEY);
      return new Promise((resolve) => {
        request.onsuccess = () => resolve(request.result ?? null);
      });
    }).then((pending) => pending);

    const report = await stored;
    if (!report) return null;
    if (report.schemaVersion !== SCHEMA_VERSION) {
      // Unsupported data is surfaced, never silently deleted (architecture §8).
      const error = new Error("The saved draft was written by a different version.");
      error.recoverable = true;
      throw error;
    }

    const blobs = new Map();
    await runTransaction(this.db, "readonly", (_reports, assets) => {
      const request = assets.getAll();
      const keys = assets.getAllKeys();
      request.onsuccess = () => {
        keys.onsuccess = () => {
          keys.result.forEach((key, index) => blobs.set(key, request.result[index]));
        };
      };
    });

    const cards = report.cards.map((card) => {
      const blob = blobs.get(card.id);
      if (!card.image || !blob) return { ...card, image: null };
      return { ...card, image: { ...card.image, objectUrl: URL.createObjectURL(blob) } };
    });
    return { cards, selectedCardId: report.selectedCardId, savedAt: report.savedAt, blobs };
  }

  async clear() {
    if (!this.db) await this.open();
    // Drop the queue so a pending autosave cannot recreate what was just cleared.
    this.queue = Promise.resolve();
    await runTransaction(this.db, "readwrite", (reports, assets) => {
      reports.delete(REPORT_KEY);
      assets.clear();
    });
    this.onStateChange(SaveState.IDLE);
  }
}
