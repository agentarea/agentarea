import { describe, expect, it } from "vitest";
import { nextCronRun } from "./nextCronRun";

const at = (iso: string) => new Date(iso);
const next = (expression: string, timeZone: string | null, after: string) =>
  nextCronRun(expression, timeZone, at(after))?.toISOString() ?? null;

describe("nextCronRun", () => {
  it("finds the next weekday morning in the trigger's timezone", () => {
    // Tuesday 10:00 in Moscow (UTC+3): today's 09:00 has passed.
    expect(next("0 9 * * 1-5", "Europe/Moscow", "2026-10-13T07:00:00Z")).toBe(
      "2026-10-14T06:00:00.000Z"
    );
    // Friday evening rolls over the weekend to Monday.
    expect(next("0 9 * * 1-5", "Europe/Moscow", "2026-10-16T18:00:00Z")).toBe(
      "2026-10-19T06:00:00.000Z"
    );
  });

  it("steps through minutes, lists and month days", () => {
    expect(next("*/15 * * * *", "UTC", "2026-10-13T10:07:30Z")).toBe(
      "2026-10-13T10:15:00.000Z"
    );
    expect(next("0 8,20 * * *", "UTC", "2026-10-13T09:00:00Z")).toBe(
      "2026-10-13T20:00:00.000Z"
    );
    expect(next("30 2 1 * *", "UTC", "2026-10-05T00:00:00Z")).toBe(
      "2026-11-01T02:30:00.000Z"
    );
  });

  it("is strictly after the given moment", () => {
    expect(next("0 9 * * *", "UTC", "2026-10-13T09:00:00Z")).toBe(
      "2026-10-14T09:00:00.000Z"
    );
  });

  it("matches either day field when both are restricted", () => {
    // The 13th, or any Friday: Friday 16 Oct comes before 13 Nov.
    expect(next("0 0 13 * 5", "UTC", "2026-10-14T00:00:00Z")).toBe(
      "2026-10-16T00:00:00.000Z"
    );
  });

  it("keeps the wall-clock time across a DST change", () => {
    // New York leaves daylight time on 1 Nov 2026: 09:00 is 14:00 UTC after.
    expect(next("0 9 * * *", "America/New_York", "2026-11-01T12:00:00Z")).toBe(
      "2026-11-01T14:00:00.000Z"
    );
    expect(next("0 9 * * *", "America/New_York", "2026-10-30T12:00:00Z")).toBe(
      "2026-10-30T13:00:00.000Z"
    );
  });

  it("reads names, Sunday as 7 and a leading seconds field", () => {
    expect(next("0 9 * * SUN", "UTC", "2026-10-13T00:00:00Z")).toBe(
      "2026-10-18T09:00:00.000Z"
    );
    expect(next("0 9 * * 7", "UTC", "2026-10-13T00:00:00Z")).toBe(
      "2026-10-18T09:00:00.000Z"
    );
    expect(next("0 0 9 * * *", "UTC", "2026-10-13T10:00:00Z")).toBe(
      "2026-10-14T09:00:00.000Z"
    );
  });

  it("gives nothing for what it cannot read", () => {
    expect(next("not a cron", "UTC", "2026-10-13T00:00:00Z")).toBeNull();
    expect(next("61 * * * *", "UTC", "2026-10-13T00:00:00Z")).toBeNull();
    expect(nextCronRun(null, "UTC", at("2026-10-13T00:00:00Z"))).toBeNull();
    // An unknown timezone falls back to UTC rather than failing.
    expect(next("0 9 * * *", "Mars/Olympus", "2026-10-13T00:00:00Z")).toBe(
      "2026-10-13T09:00:00.000Z"
    );
  });
});
