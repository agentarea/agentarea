import { afterEach, describe, expect, it } from "vitest";
import { formatRelativeTime, getValidTimestamp } from "./dateUtils";

const originalTimeZone = process.env.TZ;

afterEach(() => {
  if (originalTimeZone === undefined) {
    delete process.env.TZ;
  } else {
    process.env.TZ = originalTimeZone;
  }
});

describe("server timestamp parsing", () => {
  it("interprets offsetless ISO timestamps as UTC outside UTC", () => {
    process.env.TZ = "Europe/Moscow";
    const timestamp = new Date().toISOString().slice(0, -1);

    expect(getValidTimestamp(timestamp)).toBe(Date.parse(`${timestamp}Z`));
    expect(formatRelativeTime(timestamp)).toContain("less than a minute");
  });
});
