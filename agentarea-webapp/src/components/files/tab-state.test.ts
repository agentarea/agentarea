import { describe, expect, it } from "vitest";
import {
  closeTab,
  openTab,
  pruneTabs,
  showFolder,
  withActive,
  type TabState,
} from "./tab-state";

const state = (open: string[], active: string | null): TabState => ({
  open,
  active,
});

describe("openTab", () => {
  it("appends a file and focuses it", () => {
    expect(openTab(state([], null), "a.md")).toEqual(state(["a.md"], "a.md"));
  });

  it("focuses a file that is already open without opening it twice", () => {
    expect(openTab(state(["a.md", "b.md"], "b.md"), "a.md")).toEqual(
      state(["a.md", "b.md"], "a.md")
    );
  });

  it("keeps tab order stable as focus moves, so tabs never jump", () => {
    let current = state(["a.md", "b.md", "c.md"], "c.md");
    current = openTab(current, "a.md");
    current = openTab(current, "b.md");
    expect(current.open).toEqual(["a.md", "b.md", "c.md"]);
  });
});

describe("closeTab", () => {
  it("focuses the tab to the right of the one that closed", () => {
    expect(closeTab(state(["a.md", "b.md", "c.md"], "b.md"), "b.md")).toEqual(
      state(["a.md", "c.md"], "c.md")
    );
  });

  it("falls back to the left when the last tab closes", () => {
    expect(closeTab(state(["a.md", "b.md"], "b.md"), "b.md")).toEqual(
      state(["a.md"], "a.md")
    );
  });

  it("returns to the folder once nothing is left open", () => {
    expect(closeTab(state(["a.md"], "a.md"), "a.md")).toEqual(state([], null));
  });

  it("leaves focus alone when some other tab closes", () => {
    expect(closeTab(state(["a.md", "b.md"], "a.md"), "b.md")).toEqual(
      state(["a.md"], "a.md")
    );
  });

  it("ignores a path that is not open", () => {
    const current = state(["a.md"], "a.md");
    expect(closeTab(current, "gone.md")).toEqual(current);
  });
});

describe("showFolder", () => {
  it("drops focus without closing anything", () => {
    expect(showFolder(state(["a.md"], "a.md"))).toEqual(state(["a.md"], null));
  });
});

describe("pruneTabs", () => {
  it("closes tabs whose file is gone after a delete or a move", () => {
    expect(
      pruneTabs(state(["a.md", "b.md", "c.md"], "b.md"), ["a.md", "c.md"])
    ).toEqual(state(["a.md", "c.md"], "c.md"));
  });

  it("leaves a matching set untouched", () => {
    const current = state(["a.md"], "a.md");
    expect(pruneTabs(current, ["a.md", "b.md"])).toEqual(current);
  });

  it("returns to the folder when every open file disappears", () => {
    expect(pruneTabs(state(["a.md"], "a.md"), [])).toEqual(state([], null));
  });
});

describe("withActive", () => {
  it("focuses a file that is already open", () => {
    expect(withActive(["a.md", "b.md"], "a.md")).toEqual(
      state(["a.md", "b.md"], "a.md")
    );
  });

  it("opens a tab for a file the URL names but memory has not got", () => {
    expect(withActive(["a.md"], "shared.md")).toEqual(
      state(["a.md", "shared.md"], "shared.md")
    );
  });

  it("opens the single tab a pasted link asks for", () => {
    expect(withActive([], "shared.md")).toEqual(
      state(["shared.md"], "shared.md")
    );
  });

  it("shows the folder when the URL names no file", () => {
    expect(withActive(["a.md"], null)).toEqual(state(["a.md"], null));
  });
});
