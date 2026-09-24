// Which cards are selected for a batch action: copy, download, print or
// delete a subset of the report.
//
// Page-only state, deliberately. It is not part of a card and never reaches
// IndexedDB, so a reload starts with nothing selected rather than with a
// selection the person has forgotten about, which matters most before a
// batch delete.

const selected = new Set();
const listeners = new Set();

function emit() {
  for (const listener of listeners) listener(new Set(selected));
}

export function onSelectionChange(listener) {
  listeners.add(listener);
}

export function isSelected(id) {
  return selected.has(id);
}

export function selectedCount() {
  return selected.size;
}

export function setSelected(id, on) {
  if (on === selected.has(id)) return;
  if (on) selected.add(id);
  else selected.delete(id);
  emit();
}

export function selectOnly(ids) {
  selected.clear();
  for (const id of ids) selected.add(id);
  emit();
}

export function clearSelection() {
  if (!selected.size) return;
  selected.clear();
  emit();
}

/** Forget ids whose cards no longer exist. */
export function prune(existingIds) {
  const keep = new Set(existingIds);
  let changed = false;
  for (const id of [...selected]) {
    if (!keep.has(id)) {
      selected.delete(id);
      changed = true;
    }
  }
  if (changed) emit();
}
