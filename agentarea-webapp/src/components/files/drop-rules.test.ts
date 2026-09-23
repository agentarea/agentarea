import { describe, expect, it } from "vitest";
import { canMoveInto } from "./drop-rules";

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
});
