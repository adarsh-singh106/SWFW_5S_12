/** Keep one interactive dialog at a time and restore pre-existing inert state. */
const dialogs = [];
const originalInert = new Map();
const originalZIndex = new Map();

function synchronize() {
  const top = dialogs.at(-1)?.modal;
  for (const child of document.body?.children || []) {
    if (top && !originalInert.has(child)) originalInert.set(child, child.inert);
    if (top) child.inert = child !== top;
  }
  for (const [element, value] of originalInert) {
    if (!top) element.inert = value;
  }
  if (!top) originalInert.clear();
  dialogs.forEach(({ modal }, index) => { modal.style.zIndex = String(1000 + index); });
}

export function isTopDialog(modal) { return dialogs.at(-1)?.modal === modal; }

export function activateDialog(modal, { priority = false } = {}) {
  if (dialogs.some(entry => entry.modal === modal)) return;
  originalZIndex.set(modal, modal.style.zIndex);
  const top = dialogs.at(-1);
  const insertBelowPriority = !priority && top?.priority;
  const entry = { modal, priority, returnFocus: insertBelowPriority ? top.returnFocus : document.activeElement };
  if (insertBelowPriority) dialogs.splice(dialogs.length - 1, 0, entry);
  else dialogs.push(entry);
  synchronize();
}

export function deactivateDialog(modal) {
  const index = dialogs.findIndex(entry => entry.modal === modal);
  if (index === -1) return;
  const [{ returnFocus }] = dialogs.splice(index, 1);
  for (const entry of dialogs.slice(index)) {
    if (modal.contains?.(entry.returnFocus)) entry.returnFocus = returnFocus;
  }
  synchronize();
  modal.style.zIndex = originalZIndex.get(modal) || "";
  originalZIndex.delete(modal);
  const top = dialogs.at(-1)?.modal;
  if (index < dialogs.length) return;
  if (returnFocus?.isConnected && (!top || top.contains?.(returnFocus))) {
    returnFocus.focus();
  } else if (top) {
    top.querySelector?.('button:not([disabled]), input:not([disabled]), [tabindex="0"]')?.focus();
  }
}
