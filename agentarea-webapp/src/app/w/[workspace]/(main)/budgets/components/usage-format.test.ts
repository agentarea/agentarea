import { describe, expect, it } from "vitest";
import { splitBytes } from "./usage-format";

describe("splitBytes", () => {
  it("names a tenth of a mebibyte in KiB, not 0.0 GiB", () => {
    expect(splitBytes(0.1 / 1024)).toEqual({ value: 102.4, unit: "KiB" });
  });

  it("keeps gibibytes as they are", () => {
    expect(splitBytes(2.5)).toEqual({ value: 2.5, unit: "GiB" });
  });

  it("reads nothing stored as 0 B", () => {
    expect(splitBytes(0)).toEqual({ value: 0, unit: "B" });
  });
});
