import { describe, expect, it } from "vitest";
import { canMoveInto, isTaskOwned } from "./drop-rules";

describe("isTaskOwned", () => {
  it("covers the tasks folder and everything under it", () => {
    expect(isTaskOwned("tasks")).toBe(true);
    expect(isTaskOwned("tasks/t-1/workspace/out.txt")).toBe(true);
  });

  it("does not catch a folder merely starting with the same letters", () => {
    expect(isTaskOwned("tasksy")).toBe(false);
    expect(isTaskOwned("my-tasks/notes.md")).toBe(false);
  });
});

describe("canMoveInto", () => {
  it("allows a move to an unrelated folder", () => {
    expect(canMoveInto("wiki/index.md", "docs")).toBe(true);
  });

  it("allows a move up to the workspace root", () => {
    expect(canMoveInto("wiki/index.md", "")).toBe(true);
  });

  it("refuses a move into the folder the item already sits in", () => {
    expect(canMoveInto("wiki/index.md", "wiki")).toBe(false);
    expect(canMoveInto("notes.md", "")).toBe(false);
  });

  it("refuses a folder into itself", () => {
    expect(canMoveInto("wiki", "wiki")).toBe(false);
  });

  it("refuses a folder into its own subtree", () => {
    expect(canMoveInto("wiki", "wiki/api")).toBe(false);
    expect(canMoveInto("wiki", "wiki/api/v2")).toBe(false);
  });

  it("allows a sibling whose name merely shares a prefix", () => {
    expect(canMoveInto("wiki", "wiki-archive")).toBe(true);
  });

  it("refuses task-owned paths at either end", () => {
    expect(canMoveInto("tasks/t-1/workspace/out.txt", "docs")).toBe(false);
    expect(canMoveInto("wiki/index.md", "tasks")).toBe(false);
    expect(canMoveInto("wiki/index.md", "tasks/t-1/workspace")).toBe(false);
  });
});
