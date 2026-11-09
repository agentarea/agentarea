import { describe, expect, it } from "vitest";
import { firstLine, groupStopped } from "./stopped";

const failed = (
  task_id: string,
  agent_id: string,
  error: string | null,
  hour: number
) => ({
  task_id,
  agent_id,
  error,
  occurred_at: new Date(Date.UTC(2026, 9, 2, hour)).toISOString(),
});

describe("firstLine", () => {
  it("keeps the first line and reads an empty one as missing", () => {
    expect(firstLine("Timeout\n  at fetch")).toBe("Timeout");
    expect(firstLine("\nrest")).toBeNull();
    expect(firstLine(null)).toBeNull();
  });
});

describe("groupStopped", () => {
  it("folds the same agent and first error line into one counted row", () => {
    const groups = groupStopped(
      [],
      [
        failed("t1", "a1", "Timeout\ntrace one", 9),
        failed("t2", "a1", "Timeout\ntrace two", 11),
        failed("t3", "a1", "Timeout", 10),
      ]
    );
    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({
      kind: "failed",
      count: 3,
      reason: "Timeout",
    });
    expect(groups[0].latest.task_id).toBe("t2");
  });

  it("keeps different agents, errors and kinds apart", () => {
    const groups = groupStopped(
      [{ ...failed("b1", "a1", "Timeout", 8), description: "Sync" }],
      [
        failed("t1", "a1", "Timeout", 9),
        failed("t2", "a2", "Timeout", 10),
        failed("t3", "a1", "Rate limited", 11),
      ]
    );
    expect(groups.map((g) => g.latest.task_id)).toEqual([
      "t3",
      "t2",
      "t1",
      "b1",
    ]);
    expect(groups.every((g) => g.count === 1)).toBe(true);
  });

  it("falls back to the description when a blocked run has no error", () => {
    const groups = groupStopped(
      [
        { ...failed("b1", "a1", null, 8), description: "Sync CRM" },
        { ...failed("b2", "a1", null, 9), description: "Sync CRM" },
        { ...failed("b3", "a1", null, 10), description: "Send digest" },
      ],
      []
    );
    expect(groups.map((g) => [g.reason, g.count])).toEqual([
      ["Send digest", 1],
      ["Sync CRM", 2],
    ]);
  });
});
