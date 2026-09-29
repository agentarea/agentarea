import { describe, expect, it } from "vitest";
import { getTaskStatusPresentation } from "./status";
import {
  filterValueFor,
  statusesForFilter,
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

  it("offers one option per status as it reads on screen", () => {
    const labels = TASK_STATUS_FILTER_OPTIONS.map(
      (option) => getTaskStatusPresentation(option.value).label
    );
    expect(new Set(labels).size).toBe(labels.length);
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
