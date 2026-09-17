/** Which files are open in the browser's tab strip, and which one is showing.
 *
 * The folder itself occupies the first tab and is never closed, so `active`
 * being null means "the folder listing", not "nothing". Kept free of React so
 * the focus rules can be tested directly. */
export interface TabState {
  /** Open file paths, in the order their tabs appear after the folder tab. */
  open: string[];
  /** The file on screen, or null while the folder listing is showing. */
  active: string | null;
}

/** The tab strip's value for the folder itself.
 *
 * A dot cannot be a stored path — both the upload endpoint and the new-folder
 * dialog reject "." as a name — so no file can ever be mistaken for it. */
export const FOLDER_TAB = ".";

export function openTab(state: TabState, path: string): TabState {
  return {
    open: state.open.includes(path) ? state.open : [...state.open, path],
    active: path,
  };
}

export function showFolder(state: TabState): TabState {
  return { open: state.open, active: null };
}

export function closeTab(state: TabState, path: string): TabState {
  const index = state.open.indexOf(path);
  if (index === -1) return state;
  const open = state.open.filter((item) => item !== path);
  if (state.active !== path) return { open, active: state.active };
  // Editors hand focus to the neighbour on the right, falling back to the left
  // at the end of the strip; with the strip empty the folder takes over.
  return { open, active: open[index] ?? open[index - 1] ?? null };
}

/** Close tabs whose file no longer exists, e.g. after a delete or a move. */
export function pruneTabs(state: TabState, existing: Iterable<string>): TabState {
  const paths = new Set(existing);
  return state.open
    .filter((path) => !paths.has(path))
    .reduce(closeTab, state);
}

/** Combine the tab set, which lives in memory, with the file named by the URL.
 *
 * Only the file on screen is worth putting in a link — a session with dozens
 * of tabs would otherwise drag every one of them through the address bar. The
 * named file therefore may not be open yet: a pasted link, or the back button
 * reaching a file whose tab was closed since. */
export function withActive(open: string[], active: string | null): TabState {
  if (!active) return { open, active: null };
  return { open: open.includes(active) ? open : [...open, active], active };
}
