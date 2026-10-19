import { describe, expect, it } from "vitest";
import {
  earliestScheduleTime,
  fromLocalInputValue,
  toLocalInputValue,
} from "./scheduleTime";

describe("scheduleTime", () => {
  it("round-trips a local wall time through the input value", () => {
    const date = new Date(2026, 9, 4, 9, 5);
    expect(toLocalInputValue(date)).toBe("2026-10-04T09:05");
    expect(fromLocalInputValue("2026-10-04T09:05")?.getTime()).toBe(
      date.getTime()
    );
  });

  it("reads an empty or unreadable value as no time", () => {
    expect(fromLocalInputValue("")).toBeNull();
    expect(fromLocalInputValue("not a time")).toBeNull();
  });

  it("books no earlier than the next whole minute", () => {
    const now = new Date(2026, 9, 4, 23, 59, 30, 500);
    expect(earliestScheduleTime(now)).toEqual(new Date(2026, 9, 5, 0, 0));
  });
});
