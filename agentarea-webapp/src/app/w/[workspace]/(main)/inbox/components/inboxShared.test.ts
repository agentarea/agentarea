import { describe, expect, it } from "vitest";
import {
  countInbox,
  inboxBucket,
  isPending,
  RESOLVED_ESCALATION_STATUS,
} from "./inboxShared";

describe("inboxBucket", () => {
  it("files every status the inbox endpoint returns", () => {
    expect(inboxBucket("waiting_for_approval")).toBe("pending");
    expect(inboxBucket("waiting_for_input")).toBe("input");
    expect(inboxBucket("completed")).toBe("completed");
    expect(inboxBucket("failed")).toBe("failed");
  });

  it("files nothing it does not know under failed", () => {
    expect(inboxBucket("running")).toBeNull();
    expect(inboxBucket("something_new")).toBeNull();
  });
});

describe("isPending", () => {
  it("is an approval waiting on a person, not an input request", () => {
    expect(isPending("waiting_for_approval")).toBe(true);
    expect(isPending("waiting_for_input")).toBe(false);
  });
});

describe("countInbox", () => {
  it("counts input requests apart from failures", () => {
    const { counts, unknown } = countInbox([
      "waiting_for_input",
      "waiting_for_input",
      "failed",
      "waiting_for_approval",
      "completed",
    ]);

    expect(counts).toEqual({
      all: 5,
      pending: 1,
      input: 2,
      completed: 1,
      failed: 1,
    });
    expect(unknown).toEqual([]);
  });

  it("counts a resolved escalation as having left the inbox, not as failed", () => {
    const { counts, unknown } = countInbox([RESOLVED_ESCALATION_STATUS]);

    expect(counts.failed).toBe(0);
    expect(counts.pending).toBe(0);
    expect(unknown).toEqual([]);
  });

  it("reports a status it cannot file instead of guessing", () => {
    const { counts, unknown } = countInbox(["something_new"]);

    expect(counts).toEqual({
      all: 1,
      pending: 0,
      input: 0,
      completed: 0,
      failed: 0,
    });
    expect(unknown).toEqual(["something_new"]);
  });
});
