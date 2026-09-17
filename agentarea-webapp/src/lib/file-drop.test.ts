import { describe, expect, it, vi } from "vitest";
import {
  collectDroppedFiles,
  createDragTracker,
  dispatchDrop,
  DRAG_PATH_TYPE,
  dragKind,
  readDragPayload,
} from "./file-drop";

function fileEntry(name: string) {
  return {
    isFile: true,
    isDirectory: false,
    name,
    file: (resolve: (file: File) => void) =>
      resolve(new File([name], name, { type: "text/plain" })),
  };
}

/** `batches` mimics readEntries(): each call drains one batch, then reports empty. */
function directoryEntry(name: string, batches: unknown[][]) {
  const remaining = [...batches, []];
  return {
    isFile: false,
    isDirectory: true,
    name,
    createReader: () => ({
      readEntries: (resolve: (entries: unknown[]) => void) =>
        resolve(remaining.shift() ?? []),
    }),
  };
}

function dataTransfer({
  entries = [],
  files = [],
  types = [],
  data = {},
}: {
  entries?: unknown[];
  files?: File[];
  types?: string[];
  data?: Record<string, string>;
} = {}) {
  return {
    types,
    files,
    items: entries.map((entry) => ({
      kind: "file",
      webkitGetAsEntry: () => entry,
    })),
    getData: (type: string) => data[type] ?? "",
  } as unknown as DataTransfer;
}

describe("collectDroppedFiles", () => {
  it("keeps the folder structure as a relative path", async () => {
    const dt = dataTransfer({
      entries: [
        directoryEntry("wiki", [
          [fileEntry("index.md"), directoryEntry("api", [[fileEntry("auth.md")]])],
        ]),
      ],
    });

    const dropped = await collectDroppedFiles(dt);

    expect(dropped.map((d) => d.relativePath)).toEqual([
      "wiki/index.md",
      "wiki/api/auth.md",
    ]);
  });

  it("names a loose file by itself", async () => {
    const dt = dataTransfer({ entries: [fileEntry("notes.md")] });

    const dropped = await collectDroppedFiles(dt);

    expect(dropped.map((d) => d.relativePath)).toEqual(["notes.md"]);
    expect(dropped[0].file).toBeInstanceOf(File);
  });

  it("drains every readEntries batch, not just the first", async () => {
    // readEntries caps a single call at ~100 entries, so a large folder only
    // arrives in full if the reader is called until it reports empty.
    const first = Array.from({ length: 100 }, (_, i) => fileEntry(`a${i}.txt`));
    const second = Array.from({ length: 50 }, (_, i) => fileEntry(`b${i}.txt`));
    const dt = dataTransfer({ entries: [directoryEntry("bulk", [first, second])] });

    const dropped = await collectDroppedFiles(dt);

    expect(dropped).toHaveLength(150);
    expect(dropped.at(-1)?.relativePath).toBe("bulk/b49.txt");
  });

  it("falls back to the flat file list when the entries API is unavailable", async () => {
    const file = new File(["x"], "plain.txt");
    const dt = dataTransfer({ entries: [], files: [file] });

    const dropped = await collectDroppedFiles(dt);

    expect(dropped).toEqual([{ file, relativePath: "plain.txt" }]);
  });

  it("returns nothing for an empty drop", async () => {
    expect(await collectDroppedFiles(dataTransfer())).toEqual([]);
  });
});

describe("dragKind", () => {
  it("classifies a hovering drag without reading its payload", () => {
    const dt = dataTransfer({
      types: [DRAG_PATH_TYPE],
      // Browsers withhold getData() until drop; the zone must not depend on it.
      data: {},
    });

    expect(dragKind(dt)).toBe("path");
    expect(readDragPayload(dt)).toBeNull();
  });

  it("ignores an unrelated drag", () => {
    expect(dragKind(dataTransfer({ types: ["text/html"] }))).toBeNull();
  });
});

describe("readDragPayload", () => {
  it("reports an OS file drag", () => {
    expect(readDragPayload(dataTransfer({ types: ["Files"] }))).toEqual({
      kind: "files",
    });
  });

  it("reports an internal path drag", () => {
    const dt = dataTransfer({
      types: [DRAG_PATH_TYPE],
      data: { [DRAG_PATH_TYPE]: "wiki/index.md" },
    });

    expect(readDragPayload(dt)).toEqual({ kind: "path", path: "wiki/index.md" });
  });

  it("prefers files when a drag carries both", () => {
    const dt = dataTransfer({
      types: ["Files", DRAG_PATH_TYPE],
      data: { [DRAG_PATH_TYPE]: "wiki/index.md" },
    });

    expect(readDragPayload(dt)).toEqual({ kind: "files" });
  });

  it("ignores a drag carrying neither", () => {
    expect(readDragPayload(dataTransfer({ types: ["text/plain"] }))).toBeNull();
  });
});

describe("dispatchDrop", () => {
  it("routes an OS drag to the file handler", async () => {
    const onFiles = vi.fn();
    const onMove = vi.fn();

    dispatchDrop(
      dataTransfer({ types: ["Files"], entries: [fileEntry("notes.md")] }),
      { onFiles, onMove }
    );
    await vi.waitFor(() => expect(onFiles).toHaveBeenCalledOnce());

    expect(onFiles.mock.calls[0][0]).toMatchObject([{ relativePath: "notes.md" }]);
    expect(onMove).not.toHaveBeenCalled();
  });

  it("routes an in-app drag to the move handler", () => {
    const onFiles = vi.fn();
    const onMove = vi.fn();

    dispatchDrop(
      dataTransfer({
        types: [DRAG_PATH_TYPE],
        data: { [DRAG_PATH_TYPE]: "wiki/index.md" },
      }),
      { onFiles, onMove }
    );

    expect(onMove).toHaveBeenCalledWith("wiki/index.md");
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("does nothing when the zone has no handler for the payload", () => {
    const onMove = vi.fn();

    dispatchDrop(dataTransfer({ types: ["Files"] }), { onMove });

    expect(onMove).not.toHaveBeenCalled();
  });

  it("skips the file handler when the drop turns out to be empty", async () => {
    const onFiles = vi.fn();

    dispatchDrop(dataTransfer({ types: ["Files"] }), { onFiles });
    await Promise.resolve();

    expect(onFiles).not.toHaveBeenCalled();
  });
});

describe("createDragTracker", () => {
  it("stays active while the cursor crosses child elements", () => {
    const tracker = createDragTracker();

    expect(tracker.enter()).toBe(true); // zone
    expect(tracker.enter()).toBe(false); // child
    expect(tracker.leave()).toBe(false); // back onto the zone, still inside
    expect(tracker.active).toBe(true);
    expect(tracker.leave()).toBe(true); // finally out
    expect(tracker.active).toBe(false);
  });

  it("does not go negative when a leave arrives without its enter", () => {
    const tracker = createDragTracker();

    tracker.leave();
    expect(tracker.enter()).toBe(true);
  });

  it("resets on drop", () => {
    const tracker = createDragTracker();

    tracker.enter();
    tracker.enter();
    tracker.reset();

    expect(tracker.active).toBe(false);
    expect(tracker.enter()).toBe(true);
  });
});
