import { describe, expect, it } from "vitest";
import type { TreeNode } from "./file-tree";
import { isEntrySortKey, sortEntries } from "./sort-entries";

const file = (
  path: string,
  size?: number | null,
  last_modified?: string | null
): TreeNode => ({
  name: path.split("/").pop() ?? path,
  path,
  isFile: true,
  file: { path, size, last_modified },
  children: new Map(),
});

const folder = (path: string): TreeNode => ({
  name: path,
  path,
  isFile: false,
  children: new Map(),
});

const names = (entries: TreeNode[]) => entries.map((entry) => entry.name);

describe("sortEntries", () => {
  const entries = [
    file("report.pdf", 2048, "2026-09-01T10:00:00Z"),
    folder("wiki"),
    file("notes.md", 12, "2026-09-20T10:00:00Z"),
    folder("assets"),
    file("sandbox.log", null, null),
  ];

  it("orders by name with folders first", () => {
    expect(
      names(sortEntries(entries, { accessor: "name", direction: "asc" }))
    ).toEqual(["assets", "wiki", "notes.md", "report.pdf", "sandbox.log"]);
  });

  it("keeps folders first when the name order is reversed", () => {
    expect(
      names(sortEntries(entries, { accessor: "name", direction: "desc" }))
    ).toEqual(["wiki", "assets", "sandbox.log", "report.pdf", "notes.md"]);
  });

  it("orders files by size and leaves an unknown size last either way", () => {
    expect(
      names(sortEntries(entries, { accessor: "size", direction: "asc" }))
    ).toEqual(["assets", "wiki", "notes.md", "report.pdf", "sandbox.log"]);
    expect(
      names(sortEntries(entries, { accessor: "size", direction: "desc" }))
    ).toEqual(["assets", "wiki", "report.pdf", "notes.md", "sandbox.log"]);
  });

  it("orders files by modification date", () => {
    expect(
      names(sortEntries(entries, { accessor: "modified", direction: "desc" }))
    ).toEqual(["assets", "wiki", "notes.md", "report.pdf", "sandbox.log"]);
  });

  it("does not reorder the array it was given", () => {
    const before = names(entries);
    sortEntries(entries, { accessor: "size", direction: "desc" });
    expect(names(entries)).toEqual(before);
  });
});

describe("isEntrySortKey", () => {
  it("accepts only the columns the folder table can sort", () => {
    expect(isEntrySortKey("size")).toBe(true);
    expect(isEntrySortKey("actions")).toBe(false);
  });
});
