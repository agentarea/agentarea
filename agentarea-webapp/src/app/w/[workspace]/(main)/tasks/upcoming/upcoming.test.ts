import { describe, expect, it } from "vitest";
import type { FrequentSchedule, ScheduledRun } from "@/api/client";
import { expectedRuns } from "./upcoming";

const now = new Date("2026-11-23T12:00:00Z");
const run = (at: string, trigger: string | null, task: string | null = null) =>
  ({
    fires_at: at,
    trigger_id: trigger,
    task_id: task,
    agent_id: "a",
    agent_name: "Agent",
    title: trigger ?? task ?? "",
  }) as ScheduledRun;

describe("expectedRuns", () => {
  it("lists each trigger once, by its next firing, and every booked task", () => {
    const got = expectedRuns(
      [
        run("2026-11-27T16:00:00Z", "weekly"),
        run("2026-12-04T16:00:00Z", "weekly"),
        run("2026-11-24T09:00:00Z", null, "booked"),
        run("2026-11-22T09:00:00Z", "past"),
      ],
      [],
      now
    );
    expect(got.map((r) => r.title)).toEqual(["booked", "weekly"]);
    expect(got[1].firesAt).toBe("2026-11-27T16:00:00Z");
  });

  it("puts frequent triggers in order by their next run", () => {
    const frequent = {
      trigger_id: "mail",
      agent_id: "a",
      agent_name: null,
      title: "mail",
      cron_expression: "*/15 * * * *",
      runs_per_day: 96,
      next_run_at: "2026-11-23T12:15:00Z",
    } as FrequentSchedule;
    const got = expectedRuns(
      [run("2026-11-27T16:00:00Z", "weekly")],
      [frequent],
      now
    );
    expect(got.map((r) => r.title)).toEqual(["mail", "weekly"]);
  });
});
