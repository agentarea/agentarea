/** Drag-and-drop plumbing shared by every drop surface in the app.
 *
 * Everything here is deliberately free of React and of the DOM event system:
 * the parts that are easy to get wrong — draining the directory reader, and
 * tracking whether the cursor is still inside a zone — are plain functions so
 * they can be tested directly. `useFileDrop` is the thin wrapper over them.
 */

/** Custom MIME carrying the workspace path of an item dragged inside the app. */
export const DRAG_PATH_TYPE = "application/x-agentarea-path";

export type DroppedFile = { file: File; relativePath: string };

export type DragPayload =
  | { kind: "files" }
  | { kind: "path"; path: string }
  | null;

/** Classify a drag from its types alone.
 *
 * While a drag is merely hovering, browsers withhold the payload — only
 * `types` is readable — so this is all a zone can go on to decide whether to
 * light up and what `dropEffect` to advertise.
 */
export function dragKind(dataTransfer: DataTransfer): "files" | "path" | null {
  const types = Array.from(dataTransfer.types ?? []);
  if (types.includes("Files")) return "files";
  if (types.includes(DRAG_PATH_TYPE)) return "path";
  return null;
}

/** Classify a drag and read its payload. Only valid inside a `drop` handler. */
export function readDragPayload(dataTransfer: DataTransfer): DragPayload {
  const kind = dragKind(dataTransfer);
  if (kind === "files") return { kind: "files" };
  if (kind === "path") {
    const path = dataTransfer.getData(DRAG_PATH_TYPE);
    if (path) return { kind: "path", path };
  }
  return null;
}

/** Flatten a drop into files paired with the path they had on disk.
 *
 * Folders only survive the trip through the entries API; when it is missing we
 * fall back to the flat `files` list, which is what a browser without it gives
 * us anyway.
 */
export async function collectDroppedFiles(
  dataTransfer: DataTransfer
): Promise<DroppedFile[]> {
  const entries = Array.from(dataTransfer.items ?? [])
    .filter((item) => item.kind === "file")
    .map((item) => item.webkitGetAsEntry())
    .filter((entry): entry is FileSystemEntry => Boolean(entry));

  if (!entries.length) {
    return Array.from(dataTransfer.files ?? []).map((file) => ({
      file,
      relativePath: file.name,
    }));
  }

  const collected: DroppedFile[] = [];
  for (const entry of entries) await walk(entry, "", collected);
  return collected;
}

async function walk(
  entry: FileSystemEntry,
  prefix: string,
  collected: DroppedFile[]
): Promise<void> {
  const path = prefix ? `${prefix}/${entry.name}` : entry.name;
  if (entry.isFile) {
    collected.push({
      file: await fileOf(entry as FileSystemFileEntry),
      relativePath: path,
    });
    return;
  }
  if (!entry.isDirectory) return;
  const reader = (entry as FileSystemDirectoryEntry).createReader();
  for (const child of await drain(reader)) await walk(child, path, collected);
}

function fileOf(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject));
}

/** Read a directory to the end.
 *
 * `readEntries` hands back at most ~100 entries per call and signals the end
 * with an empty batch, so a single call silently truncates a large folder.
 */
async function drain(
  reader: FileSystemDirectoryReader
): Promise<FileSystemEntry[]> {
  const all: FileSystemEntry[] = [];
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
      reader.readEntries(resolve, reject)
    );
    if (!batch.length) return all;
    all.push(...batch);
  }
}

export interface DropHandlers {
  onFiles?: (files: DroppedFile[]) => void | Promise<void>;
  onMove?: (sourcePath: string) => void | Promise<void>;
}

/** Route a drop to the handler its payload belongs to.
 *
 * Call this synchronously from the `drop` handler: the entries behind an OS
 * drag are read before the first await and go stale once the event is over.
 */
export function dispatchDrop(
  dataTransfer: DataTransfer,
  { onFiles, onMove }: DropHandlers
): void {
  const payload = readDragPayload(dataTransfer);
  if (payload?.kind === "files" && onFiles) {
    const collected = collectDroppedFiles(dataTransfer);
    void collected.then((files) => (files.length ? onFiles(files) : undefined));
    return;
  }
  if (payload?.kind === "path" && onMove) void onMove(payload.path);
}

/** Track whether a drag is still inside a zone across its child elements.
 *
 * `dragenter`/`dragleave` fire for every element under the cursor, so a zone
 * that toggles on the raw events flickers as the drag crosses its children.
 * Counting depth instead keeps the zone lit until the drag truly leaves.
 */
export function createDragTracker() {
  let depth = 0;
  return {
    /** @returns whether the zone just became active. */
    enter(): boolean {
      depth += 1;
      return depth === 1;
    },
    /** @returns whether the zone just became inactive. */
    leave(): boolean {
      depth = Math.max(0, depth - 1);
      return depth === 0;
    },
    reset(): void {
      depth = 0;
    },
    get active(): boolean {
      return depth > 0;
    },
  };
}
