import { describe, expect, it } from "vitest";
import { metricsPeriodHours, parseMetricsPeriod } from "./period";

describe("metrics period", () => {
  it("reads a known period and falls back to the default otherwise", () => {
    expect(parseMetricsPeriod("7d")).toBe("7d");
    expect(parseMetricsPeriod(["30d", "7d"])).toBe("30d");
    expect(parseMetricsPeriod("1y")).toBe("24h");
    expect(parseMetricsPeriod(undefined)).toBe("24h");
  });

  it("asks for no window when the period is all time", () => {
    expect(metricsPeriodHours("24h")).toBe(24);
    expect(metricsPeriodHours("30d")).toBe(720);
    expect(metricsPeriodHours("all")).toBeUndefined();
  });
});
