import { enUS, ru } from "date-fns/locale";
import { describe, expect, it } from "vitest";
import {
  atClock,
  defaultScheduleTime,
  earliestScheduleTime,
  formatScheduleDay,
  fromLocalInputValue,
  parseScheduleClock,
  parseScheduleDay,
  schedulePresets,
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

  it("starts a fresh schedule at the next whole hour", () => {
    const now = new Date(2026, 9, 4, 14, 20);
    expect(defaultScheduleTime(now)).toEqual(new Date(2026, 9, 4, 15, 0));
  });

  it("reads a typed day in the locale's short format", () => {
    const day = new Date(2026, 9, 31);
    expect(formatScheduleDay(day, ru)).toBe("31.10.2026");
    expect(parseScheduleDay("31.10.2026", ru)).toEqual(day);
    expect(parseScheduleDay("10/31/2026", enUS)).toEqual(day);
    expect(parseScheduleDay("31/10/2026", enUS)).toBeNull();
    expect(parseScheduleDay("", ru)).toBeNull();
  });

  it("reads a typed time on a 24-hour clock", () => {
    expect(parseScheduleClock("9:05")).toEqual({ hours: 9, minutes: 5 });
    expect(parseScheduleClock(" 23.59 ")).toEqual({ hours: 23, minutes: 59 });
    expect(parseScheduleClock("24:00")).toBeNull();
    expect(parseScheduleClock("9")).toBeNull();
  });

  it("offers an hour from now and the next mornings", () => {
    // A Friday afternoon.
    const now = new Date(2026, 9, 30, 14, 20, 40);
    const presets = schedulePresets(now);
    expect(presets.inOneHour).toEqual(new Date(2026, 9, 30, 15, 20));
    expect(presets.tomorrowMorning).toEqual(new Date(2026, 9, 31, 9, 0));
    expect(presets.mondayMorning).toEqual(new Date(2026, 10, 2, 9, 0));
    expect(atClock(now, { hours: 7, minutes: 30 })).toEqual(
      new Date(2026, 9, 30, 7, 30)
    );
  });
});
