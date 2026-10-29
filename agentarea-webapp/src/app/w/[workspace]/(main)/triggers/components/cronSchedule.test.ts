import { describe, expect, it } from "vitest";
import { parseCronSchedule } from "./cronSchedule";
import { describeCronExpression } from "./triggerDisplay";

describe("what a cron expression means", () => {
  it("reads the shapes the listing names in words", () => {
    expect(parseCronSchedule("*/5 * * * *")).toEqual({
      kind: "everyMinutes",
      n: 5,
    });
    expect(parseCronSchedule("0 * * * *")).toEqual({ kind: "everyHour" });
    expect(parseCronSchedule("15 * * * *")).toEqual({
      kind: "everyHourAt",
      minute: 15,
    });
    expect(parseCronSchedule("0 */3 * * *")).toEqual({
      kind: "everyHours",
      n: 3,
    });
    expect(parseCronSchedule("0 9 * * 1-5")).toEqual({
      kind: "weekdays",
      time: { hour: 9, minute: 0 },
    });
    expect(parseCronSchedule("30 10 * * 0,6")).toEqual({
      kind: "weekends",
      time: { hour: 10, minute: 30 },
    });
    expect(parseCronSchedule("0 8 * * 1")).toEqual({
      kind: "weekly",
      day: 1,
      time: { hour: 8, minute: 0 },
    });
    expect(parseCronSchedule("0 7 * * *")).toEqual({
      kind: "daily",
      time: { hour: 7, minute: 0 },
    });
    expect(parseCronSchedule("0 9 15 * *")).toEqual({
      kind: "monthly",
      day: 15,
      time: { hour: 9, minute: 0 },
    });
  });

  it("drops a leading seconds field", () => {
    expect(parseCronSchedule("0 0 9 * * 1-5")).toEqual({
      kind: "weekdays",
      time: { hour: 9, minute: 0 },
    });
  });

  it("hands back what it cannot name", () => {
    expect(parseCronSchedule(null)).toEqual({ kind: "none" });
    expect(parseCronSchedule("0 9 * 1 *")).toEqual({
      kind: "raw",
      expr: "0 9 * 1 *",
    });
    expect(parseCronSchedule("not cron")).toEqual({
      kind: "raw",
      expr: "not cron",
    });
  });
});

describe("the English phrase the listing shows", () => {
  it("is unchanged by the parser underneath", () => {
    expect(describeCronExpression("*/5 * * * *")).toBe("Every 5 minutes");
    expect(describeCronExpression("0 9 * * 1-5")).toBe("Weekdays at 9:00 AM");
    expect(describeCronExpression("0 0 * * *")).toBe("Every day at midnight");
    expect(describeCronExpression("0 8 * * 1")).toBe("Every Monday at 8:00 AM");
    expect(describeCronExpression("0 9 2 * *")).toBe(
      "Monthly on the 2nd at 9:00 AM"
    );
    expect(describeCronExpression(null)).toBe("Custom schedule");
  });
});
