import { describe, expect, it } from "vitest";
import { usefulFilterTabs } from "./filterTabs";

const values = (tabs: { value: string }[]) => tabs.map((tab) => tab.value);

describe("usefulFilterTabs", () => {
  it("hides a filter whose every tab is empty or the whole list", () => {
    const tabs = [
      { value: "all", count: 17 },
      { value: "private", count: 17 },
      { value: "inbound", count: 0 },
      { value: "outbound", count: 0 },
    ];
    expect(usefulFilterTabs(tabs, "all")).toEqual([]);
  });

  it("keeps the tabs that narrow the list and drops the empty ones", () => {
    const tabs = [
      { value: "all", count: 3 },
      { value: "attention", count: 2 },
      { value: "unused", count: 0 },
      { value: "unrestricted", count: 2 },
    ];
    expect(values(usefulFilterTabs(tabs, "all"))).toEqual([
      "all",
      "attention",
      "unrestricted",
    ]);
  });

  it("drops a tab that holds the whole list beside one that narrows it", () => {
    const tabs = [
      { value: "all", count: 5 },
      { value: "schedule", count: 5 },
      { value: "event", count: 2 },
    ];
    expect(values(usefulFilterTabs(tabs, "all"))).toEqual(["all", "event"]);
  });

  it("keeps the selected tab even when it is empty, so the way back stays", () => {
    const tabs = [
      { value: "all", count: 3 },
      { value: "channel", count: 0 },
      { value: "schedule", count: 3 },
    ];
    expect(values(usefulFilterTabs(tabs, "channel"))).toEqual([
      "all",
      "channel",
    ]);
  });

  it("keeps every tab while the counts are still loading", () => {
    const tabs = [{ value: "all" }, { value: "private" }];
    expect(usefulFilterTabs(tabs, "all")).toBe(tabs);
  });
});
