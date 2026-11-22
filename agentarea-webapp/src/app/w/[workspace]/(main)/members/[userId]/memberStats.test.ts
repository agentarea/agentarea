import { describe, expect, it } from "vitest";
import {
  latestInstant,
  memberGrants,
  summarizeMemberTasks,
} from "./memberStats";

const task = (
  status: string,
  created_at: string,
  extra: { total_cost?: number | null; result?: unknown } = {}
) => ({ status, created_at, ...extra });

describe("summarizeMemberTasks", () => {
  it("counts running and waiting tasks and sums spend from either field", () => {
    const summary = summarizeMemberTasks(
      [
        task("running", "2026-11-20T10:00:00Z", { total_cost: 0.5 }),
        task("waiting_for_approval", "2026-11-21T10:00:00Z"),
        task("blocked", "2026-11-19T10:00:00Z"),
        task("completed", "2026-11-18T10:00:00Z", {
          total_cost: null,
          result: { total_cost: 1.25 },
        }),
      ],
      10
    );
    expect(summary).toEqual({
      count: 4,
      capped: false,
      running: 1,
      needsAction: 2,
      spend: 1.75,
      lastStartedAt: "2026-11-21T10:00:00Z",
    });
  });

  it("counts only the sample and flags the overflow row as capped", () => {
    const summary = summarizeMemberTasks(
      [
        task("completed", "2026-11-03T00:00:00Z", { total_cost: 1 }),
        task("completed", "2026-11-02T00:00:00Z", { total_cost: 1 }),
        task("completed", "2026-11-01T00:00:00Z", { total_cost: 1 }),
      ],
      2
    );
    expect(summary.count).toBe(2);
    expect(summary.capped).toBe(true);
    expect(summary.spend).toBe(2);
  });

  it("has no last start without tasks", () => {
    expect(summarizeMemberTasks([], 5).lastStartedAt).toBeNull();
  });
});

describe("latestInstant", () => {
  it("picks the later instant and skips missing or invalid ones", () => {
    expect(
      latestInstant(
        null,
        "2026-11-01T00:00:00Z",
        "nope",
        "2026-11-02T00:00:00Z"
      )
    ).toBe("2026-11-02T00:00:00Z");
    expect(latestInstant(undefined, null)).toBeNull();
  });
});

describe("memberGrants", () => {
  const rel = (
    subject: string,
    object: string,
    relation: string,
    object_name = object
  ) => ({ namespace: "Agent", object, object_name, relation, subject });

  it("keeps this person's grants, the stronger one per resource, owners first", () => {
    expect(
      memberGrants(
        [
          rel("user:u1", "a1", "user", "Zeta"),
          rel("user:u1", "a1", "owner", "Zeta"),
          rel("user:u1", "a2", "editor", "Alpha"),
          rel("user:u2", "a3", "owner"),
          rel("agent:x", "a4", "owner"),
          rel("user:u1", "a5", "connect"),
        ],
        "u1"
      )
    ).toEqual([
      {
        namespace: "Agent",
        object: "a1",
        objectName: "Zeta",
        relation: "owner",
      },
      {
        namespace: "Agent",
        object: "a2",
        objectName: "Alpha",
        relation: "editor",
      },
    ]);
  });
});
