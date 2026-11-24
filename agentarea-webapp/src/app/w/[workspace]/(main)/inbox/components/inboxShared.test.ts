import { describe, expect, it } from "vitest";
import {
  countInbox,
  decidedStatus,
  inboxBucket,
  inboxRowPreview,
  isPending,
  pruneDecided,
  RESOLVED_ESCALATION_STATUS,
} from "./inboxShared";

describe("inboxBucket", () => {
  it("files every status the inbox endpoint returns", () => {
    expect(inboxBucket("waiting_for_approval")).toBe("pending");
    expect(inboxBucket("waiting_for_input")).toBe("input");
    expect(inboxBucket("blocked")).toBe("blocked");
  });

  it("files nothing that waits on no one", () => {
    expect(inboxBucket("completed")).toBeNull();
    expect(inboxBucket("failed")).toBeNull();
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
  it("counts input requests apart from blocked runs, and decisions apart from tasks", () => {
    const { counts, unknown } = countInbox(
      [
        "waiting_for_input",
        "waiting_for_input",
        "blocked",
        "waiting_for_approval",
      ],
      3
    );

    expect(counts).toEqual({
      all: 4,
      pending: 1,
      input: 2,
      blocked: 1,
      decided: 3,
    });
    expect(unknown).toEqual([]);
  });

  it("counts a client tool call held for approval as waiting on a person", () => {
    const { counts } = countInbox(["waiting_for_approval", "blocked"], 0, 2);

    expect(counts.all).toBe(4);
    expect(counts.pending).toBe(3);
    expect(counts.blocked).toBe(1);
  });

  it("counts a resolved escalation as having left the inbox, not as blocked", () => {
    const { counts, unknown } = countInbox([RESOLVED_ESCALATION_STATUS]);

    expect(counts.blocked).toBe(0);
    expect(counts.pending).toBe(0);
    expect(unknown).toEqual([]);
  });

  it("reports a status it cannot file instead of guessing", () => {
    const { counts, unknown } = countInbox(["something_new"]);

    expect(counts).toEqual({
      all: 1,
      pending: 0,
      input: 0,
      blocked: 0,
      decided: 0,
    });
    expect(unknown).toEqual(["something_new"]);
  });
});

describe("inboxRowPreview", () => {
  it("names the prerequisite a blocked run hit", () => {
    expect(inboxRowPreview("blocked", "  No PR URL was provided. ")).toEqual({
      text: "No PR URL was provided.",
    });
    expect(inboxRowPreview("blocked", " ")).toEqual({ key: "row.blocked" });
  });

  it("says what an approval or a question waits for, whatever error it carries", () => {
    expect(inboxRowPreview("waiting_for_approval", "x")).toEqual({
      key: "row.waiting",
    });
    expect(inboxRowPreview("waiting_for_input")).toEqual({
      key: "row.needsInput",
    });
  });

  it("reads a just-decided escalation as moving on", () => {
    expect(inboxRowPreview(RESOLVED_ESCALATION_STATUS)).toEqual({
      key: "row.resuming",
    });
  });
});

// An approved item came back as "Waiting for approval": the reload landed
// before the workflow wrote the task's new status, and wiped the decision.
describe("decided escalations", () => {
  const waiting = {
    id: "t1",
    status: "waiting_for_approval",
    escalation_id: "esc-1",
  };

  it("shows a decision as made while the server still lists the task as waiting", () => {
    expect(decidedStatus(waiting, { t1: "esc-1" })).toBe(
      RESOLVED_ESCALATION_STATUS
    );
    expect(
      decidedStatus({ ...waiting, escalation_id: null }, { t1: "esc-1" })
    ).toBe(RESOLVED_ESCALATION_STATUS);
  });

  it("shows a new escalation on the same task as pending", () => {
    expect(
      decidedStatus({ ...waiting, escalation_id: "esc-2" }, { t1: "esc-1" })
    ).toBe("waiting_for_approval");
  });

  it("keeps a decision across a reload that has not caught up, and drops it once it has", () => {
    expect(pruneDecided({ t1: "esc-1" }, [waiting])).toEqual({ t1: "esc-1" });
    expect(
      pruneDecided({ t1: "esc-1" }, [{ ...waiting, status: "completed" }])
    ).toEqual({});
    expect(pruneDecided({ t1: "esc-1" }, [])).toEqual({});
  });
});
