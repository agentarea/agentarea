import { describe, expect, it } from "vitest";
import { getTaskStatusPresentation } from "./status";
import {
  filterValueFor,
  statusesForFilter,
  TASK_STATUS_FILTER_GROUPS,
  TASK_STATUS_FILTER_OPTIONS,
  TASK_STATUS_VALUES,
} from "./taskStatusFilter";

describe("TASK_STATUS_VALUES", () => {
  it("is the backend's vocabulary, including the pre-dispatch statuses", () => {
    expect(TASK_STATUS_VALUES).toEqual(
      expect.arrayContaining(["submitted", "preparing", "working", "pending"])
    );
  });
});

describe("TASK_STATUS_FILTER_OPTIONS", () => {
  it("leaves no status unfindable, and files each under exactly one option", () => {
    const filed = TASK_STATUS_FILTER_OPTIONS.flatMap(
      (option) => option.statuses
    );
    expect([...filed].sort()).toEqual([...TASK_STATUS_VALUES].sort());
  });

  it("offers one option per name", () => {
    const names = TASK_STATUS_FILTER_OPTIONS.map(
      (option) => option.labelKey ?? option.label
    );
    expect(new Set(names).size).toBe(names.length);
  });

  it("keeps apart the statuses that all read as Needs action on screen", () => {
    const attention = TASK_STATUS_FILTER_OPTIONS.filter(
      (option) => option.group === "attention"
    );
    expect(attention.map((option) => option.labelKey)).toEqual([
      "inputRequired",
      "approvalRequired",
      "continuationRequired",
      "blocked",
    ]);
    for (const option of attention) {
      expect(option.statuses).toHaveLength(1);
      expect(getTaskStatusPresentation(option.value).kind).toBe("attention");
    }
  });

  it("lists in-flight, then waiting, then finished statuses", () => {
    const groups = TASK_STATUS_FILTER_OPTIONS.map((option) => option.group);
    const order = TASK_STATUS_FILTER_GROUPS.map((group) =>
      groups.indexOf(group)
    );
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(
      TASK_STATUS_FILTER_OPTIONS.filter((option) => option.group === "finished")
        .map((option) => option.value)
    ).toEqual(["completed", "failed", "cancelled"]);
  });

  it("groups the statuses that read as Pending, and those that read as Running", () => {
    const pending = TASK_STATUS_FILTER_OPTIONS.find(
      (option) => option.value === "pending"
    );
    const running = TASK_STATUS_FILTER_OPTIONS.find(
      (option) => option.value === "running"
    );
    expect(pending?.statuses).toEqual(
      expect.arrayContaining(["pending", "submitted", "preparing"])
    );
    expect(running?.statuses).toEqual(
      expect.arrayContaining(["running", "working"])
    );
  });
});

describe("statusesForFilter", () => {
  it("expands an option to every status it stands for", () => {
    expect(statusesForFilter("running")?.sort()).toEqual([
      "running",
      "working",
    ]);
  });

  it("finds the group of a status that is not itself an option", () => {
    expect(statusesForFilter("preparing")).toEqual(
      statusesForFilter("pending")
    );
  });

  it("is null for a value the backend does not know", () => {
    expect(statusesForFilter("bogus")).toBeNull();
  });
});

describe("filterValueFor", () => {
  it("selects the option that holds the status", () => {
    expect(filterValueFor("working")).toBe("running");
    expect(filterValueFor("failed")).toBe("failed");
    expect(filterValueFor("bogus")).toBeNull();
  });
});
