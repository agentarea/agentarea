import { describe, expect, it, vi } from "vitest";
import { mergeUiPrefs, parseUiPrefs } from "./ui-prefs";

describe("parseUiPrefs", () => {
  it("returns empty prefs when there is no cookie", () => {
    expect(parseUiPrefs(undefined)).toEqual({ views: {} });
  });

  it("reads the sidebar and the views", () => {
    expect(
      parseUiPrefs(
        JSON.stringify({
          sidebarOpen: false,
          sidebarWidth: 280,
          views: { tab_tasks: "grid" },
        })
      )
    ).toEqual({
      sidebarOpen: false,
      sidebarWidth: 280,
      views: { tab_tasks: "grid" },
    });
  });

  it("drops values of the wrong type", () => {
    expect(
      parseUiPrefs(
        JSON.stringify({
          sidebarOpen: "false",
          sidebarWidth: "280",
          views: { tab_tasks: 1, view_skills: "list" },
        })
      )
    ).toEqual({ views: { view_skills: "list" } });
  });

  it("treats a malformed cookie as no cookie", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(parseUiPrefs("{not json")).toEqual({ views: {} });
    expect(parseUiPrefs("[1,2]")).toEqual({ views: {} });
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });
});

describe("mergeUiPrefs", () => {
  it("keeps the other views when one changes", () => {
    expect(
      mergeUiPrefs(
        { sidebarWidth: 240, views: { tab_tasks: "grid", tab_apps: "table" } },
        { views: { tab_tasks: "table" } }
      )
    ).toEqual({
      sidebarWidth: 240,
      views: { tab_tasks: "table", tab_apps: "table" },
    });
  });

  it("sets a sidebar field without touching the views", () => {
    expect(
      mergeUiPrefs({ views: { tab_apps: "grid" } }, { sidebarOpen: false })
    ).toEqual({ sidebarOpen: false, views: { tab_apps: "grid" } });
  });
});
