/** Which drops the workspace file manager is willing to offer.
 *
 * The API refuses these moves too, but a zone that lights up and then fails is
 * worse than one that never invites the drop, so the same rules are applied
 * before the cursor is ever released.
 */

/** Task files are owned by a task's committed manifest: not writable, not movable. */
export function isTaskOwned(path: string): boolean {
  return path === "tasks" || path.startsWith("tasks/");
}

/** Would dropping `source` into `folderPath` be a move worth performing? */
export function canMoveInto(source: string, folderPath: string): boolean {
  if (isTaskOwned(source) || isTaskOwned(folderPath)) return false;
  if (folderPath === source) return false;
  // A folder cannot swallow itself; the trailing slash keeps a sibling whose
  // name merely starts the same ("wiki-archive") out of the comparison.
  if (folderPath.startsWith(`${source}/`)) return false;
  return parentOf(source) !== folderPath;
}

function parentOf(path: string): string {
  return path.split("/").slice(0, -1).join("/");
}
